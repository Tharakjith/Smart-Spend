"""Explainable, deterministic matching engine.

Stage 1 exact identifiers -> Stage 2 normalised comparisons -> Stage 3 context. Produces *suggestions*
only; nothing here links, merges or changes totals. See docs/ARCHITECTURE.md §4.
"""
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.money import fmt
from app.models import CanonicalTransaction, Household, ReconciliationMatch, SourceRecord
from app.modules.merchants.normalize import merchant_similarity
from app.modules.merchants.service import merchants_are_aliases
from app.modules.reconciliation.config import matching_config, tolerance

ZERO = Decimal("0")
REVERSAL_WORDS = ("reversal", "reversed", "rev ", "refund", "chargeback", "failed txn", "returned")


@dataclass
class Score:
    kind: str
    a: SourceRecord
    b: SourceRecord
    score: int = 0
    reasons: list = field(default_factory=list)
    conflict: bool = False
    amount_difference: Decimal = ZERO
    date_difference_days: int = 0
    merchant_similarity: float = 0.0
    suggested_amount: Decimal | None = None

    def add(self, points: int, code: str, text: str) -> None:
        self.score += points
        self.reasons.append({"code": code, "points": points, "text": text})

    def note(self, code: str, text: str) -> None:
        self.reasons.append({"code": code, "points": 0, "text": text})


def _refs(s: SourceRecord) -> set[str]:
    return {r.strip().upper() for r in (s.upi_txn_id, s.utr, s.bank_ref) if r and r.strip()}


def _merchant_text(s: SourceRecord) -> str:
    return s.merchant_raw or s.description or ""


def _ct_type(db: Session, s: SourceRecord) -> str:
    ct = db.get(CanonicalTransaction, s.canonical_transaction_id)
    return ct.type if ct else ""


def classify_pair(db: Session, x: SourceRecord, y: SourceRecord) -> tuple[str, SourceRecord, SourceRecord] | None:
    """Returns (kind, a, b) in canonical orientation or None if the pair can never describe one event."""
    tx, ty = _ct_type(db, x), _ct_type(db, y)
    spend_types = {"expense"}
    if x.role == "bill" and y.role == "payment" and y.direction == "out" and ty in spend_types and tx in spend_types:
        return "bill_payment", x, y
    if y.role == "bill" and x.role == "payment" and x.direction == "out" and tx in spend_types and ty in spend_types:
        return "bill_payment", y, x
    if x.role == y.role and x.direction == y.direction and tx == ty:
        a, b = (x, y) if (x.created_at, str(x.id)) <= (y.created_at, str(y.id)) else (y, x)
        return "duplicate", a, b
    # Incoming money from a merchant we previously paid: candidate refund / reversal.
    if x.direction == "in" and y.direction == "out" and tx in ("refund", "income") and ty in spend_types:
        return "refund", y, x
    if y.direction == "in" and x.direction == "out" and ty in ("refund", "income") and tx in spend_types:
        return "refund", x, y
    return None


def score_pair(db: Session, household: Household, kind: str, a: SourceRecord, b: SourceRecord, cfg: dict | None = None) -> Score | None:
    cfg = cfg or matching_config(household)
    w = cfg["weights"]
    sc = Score(kind=kind, a=a, b=b)
    a_amt, b_amt = Decimal(a.amount), Decimal(b.amount)
    cur = a.currency

    # ---- Stage 1: exact identifiers
    refs_a, refs_b = _refs(a), _refs(b)
    shared = refs_a & refs_b
    if shared:
        sc.add(w["shared_reference"], "shared_reference", f"Exact transaction reference matched ({sorted(shared)[0]})")
    elif refs_a and refs_b and kind != "refund":
        return None  # both carry payment references and they differ: provably different payments
    if a.currency != b.currency:
        if not shared:
            return None
        sc.conflict = True
        sc.note("currency_conflict", f"Same reference but different currencies ({a.currency} vs {b.currency})")
    inv_same = bool(a.invoice_number and b.invoice_number and a.invoice_number.strip().upper() == b.invoice_number.strip().upper())
    if kind == "duplicate" and a.role == "bill" and a.invoice_number and b.invoice_number and not inv_same and not shared:
        return None  # two bills with different invoice numbers are different bills
    if inv_same:
        sc.add(w["invoice_number"], "invoice_number", f"Same invoice/receipt number ({a.invoice_number})")
    if a.order_id and b.order_id and a.order_id.strip().upper() == b.order_id.strip().upper():
        sc.add(w["order_id"], "order_id", f"Same order id ({a.order_id})")
    strong_id = bool(shared or inv_same)

    # ---- Stage 2: dates
    dd = abs((a.occurred_on - b.occurred_on).days)
    sc.date_difference_days = dd
    if kind == "refund":
        if b.occurred_on < a.occurred_on or (b.occurred_on - a.occurred_on).days > cfg["refund_window_days"]:
            return None
        sc.note("refund_after", f"Credit received {dd} day(s) after the original payment")
    else:
        if dd > cfg["date_window_days"] and not strong_id:
            return None
        if kind == "duplicate" and dd > 1 and not strong_id:
            return None  # same merchant & amount on different days = separate purchases (Scenario H)
        if dd == 0:
            sc.add(w["date_same_day"], "date_same_day", "Same transaction date")
        elif dd == 1:
            sc.add(w["date_one_day"], "date_one_day", "Dates are one day apart")
        elif dd <= cfg["date_window_days"]:
            sc.add(w["date_far_penalty"], "date_window", f"Dates are {dd} days apart (within the {cfg['date_window_days']}-day window)")
        else:
            sc.note("date_outside_window", f"Dates are {dd} days apart, outside the matching window")
        if a.occurred_at and b.occurred_at:
            minutes = abs((a.occurred_at - b.occurred_at).total_seconds()) / 60
            if minutes <= cfg["time_window_minutes"]:
                sc.add(w["time_close"], "time_close", f"Times are {int(minutes)} minutes apart")
            elif kind == "duplicate" and minutes > 360:
                sc.add(w["time_far_penalty"], "time_far", f"Times differ by {int(minutes // 60)} hours")

    # ---- Stage 2: merchant
    if a.merchant_id and b.merchant_id and a.merchant_id == b.merchant_id:
        sc.merchant_similarity = 1.0
        sc.add(w["merchant_same"], "merchant_same", f"Same merchant ({a.merchant_raw or b.merchant_raw})")
    elif _merchant_text(a) and _merchant_text(b):
        if merchants_are_aliases(db, a.household_id, _merchant_text(a), _merchant_text(b)):
            sc.merchant_similarity = 1.0
            sc.add(w["merchant_same"], "merchant_alias", f"'{_merchant_text(b)}' is a confirmed alias of '{_merchant_text(a)}'")
        else:
            sim = merchant_similarity(_merchant_text(a), _merchant_text(b))
            sc.merchant_similarity = sim
            if sim >= 0.9:
                sc.add(w["merchant_similar_high"], "merchant_similar", f"Merchant names are very similar ('{_merchant_text(a)}' / '{_merchant_text(b)}')")
            elif sim >= 0.75:
                sc.add(w["merchant_similar_medium"], "merchant_similar", f"Merchant names are somewhat similar ('{_merchant_text(a)}' / '{_merchant_text(b)}')")
            else:
                sc.note("merchant_different", f"Merchant names differ ('{_merchant_text(a)}' / '{_merchant_text(b)}')")
    else:
        sc.note("merchant_missing", "Merchant name is missing on one record")
    merchant_evidence = sc.merchant_similarity >= 0.75

    # ---- Stage 2: amounts
    if kind == "bill_payment":
        bill, pay = a, b
        remaining_bill = Decimal(bill.amount) - Decimal(bill.allocated_amount)
        available_pay = Decimal(pay.amount) - Decimal(pay.allocated_amount)
        diff = Decimal(pay.amount) - Decimal(bill.amount)
        sc.amount_difference = diff
        tol = tolerance(cfg, Decimal(bill.amount))
        if diff == 0:
            sc.add(w["amount_equal"], "amount_equal", f"Amounts match exactly ({fmt(bill.amount, cur)})")
            sc.suggested_amount = min(remaining_bill, available_pay)
        elif Decimal(bill.allocated_amount) > 0 and Decimal(pay.amount) == remaining_bill:
            sc.add(w["amount_equals_remaining"], "amount_equals_remaining", f"Payment equals the bill's remaining balance ({fmt(remaining_bill, cur)})")
            sc.suggested_amount = remaining_bill
        elif 0 < diff <= tol:
            sc.add(w["amount_within_tolerance"], "amount_over_small", f"Payment exceeds bill by {fmt(diff, cur)} - possible tip, service charge or delivery fee; please confirm")
            sc.suggested_amount = min(remaining_bill, available_pay)
        elif diff < 0:
            if not (merchant_evidence or strong_id):
                return None
            if shared and -diff > tol:
                sc.conflict = True
                sc.note("amount_conflict", f"Same reference but amounts differ by {fmt(-diff, cur)} - needs review")
            sc.add(w["amount_partial"], "amount_partial", f"Payment ({fmt(pay.amount, cur)}) is less than the bill ({fmt(bill.amount, cur)}) - possible partial payment; {fmt(-diff, cur)} would remain")
            sc.suggested_amount = min(remaining_bill, available_pay)
        else:  # payment much larger than bill
            if shared:
                sc.conflict = True
                sc.note("amount_conflict", f"Same reference but amounts differ by {fmt(diff, cur)} - needs review")
            elif not merchant_evidence:
                return None
            sc.add(w["amount_covers_multiple"], "amount_covers_multiple", f"Payment is {fmt(diff, cur)} more than the bill - it may cover several bills")
            sc.suggested_amount = min(remaining_bill, available_pay)
        if available_pay <= 0:
            sc.add(w["already_allocated_penalty"], "payment_already_linked", "Payment is already fully linked to another bill")
        if remaining_bill <= 0:
            sc.add(w["already_allocated_penalty"], "bill_already_paid", "Bill is already fully paid")
        if sc.suggested_amount is not None and sc.suggested_amount <= 0:
            sc.suggested_amount = None
    elif kind == "duplicate":
        diff = b_amt - a_amt
        sc.amount_difference = diff
        if diff == 0:
            sc.add(w["amount_equal"], "amount_equal", f"Amounts match exactly ({fmt(a_amt, cur)})")
        elif abs(diff) <= tolerance(cfg, a_amt) and (merchant_evidence or strong_id):
            sc.add(w["amount_partial"], "amount_close", f"Amounts differ by {fmt(abs(diff), cur)}")
        elif strong_id:
            sc.conflict = True
            sc.note("amount_conflict", f"Same reference but amounts differ by {fmt(abs(diff), cur)} - needs review")
        else:
            return None
        if a.role == "bill" and a.item_names and b.item_names:
            sa, sb = set(a.item_names), set(b.item_names)
            overlap = len(sa & sb) / max(len(sa | sb), 1)
            if overlap >= 0.8:
                sc.add(w["items_overlap"], "items_overlap", f"{int(overlap * 100)}% of line items match")
    else:  # refund
        if b_amt > a_amt:
            return None
        if not (merchant_evidence or shared):
            return None
        sc.amount_difference = b_amt - a_amt
        if b_amt == a_amt:
            sc.add(w["refund_full"], "refund_full", f"Credit equals the original payment ({fmt(a_amt, cur)}) - full refund or reversal")
        else:
            sc.add(w["refund_partial"], "refund_partial", f"Credit of {fmt(b_amt, cur)} is part of the original {fmt(a_amt, cur)} - partial refund")
        text = f"{b.description} {b.merchant_raw}".lower()
        if any(word in text for word in REVERSAL_WORDS):
            sc.add(10, "refund_keyword", "Description mentions a refund or reversal")

    sc.score = max(0, min(100, sc.score))
    return sc


def confidence_for(cfg: dict, score: int, conflict: bool) -> str | None:
    t = cfg["thresholds"]
    if conflict:
        return "medium"  # conflicts always go to review, never auto-prominent
    if score >= t["high"]:
        return "high"
    if score >= t["medium"]:
        return "medium"
    if score >= t["low"]:
        return "low"
    return None


def _eligible(db: Session, s: SourceRecord) -> bool:
    if s.status != "active" or s.canonical_transaction_id != s.original_transaction_id:
        return False
    ct = db.get(CanonicalTransaction, s.canonical_transaction_id)
    return ct is not None and ct.status == "active"


def find_counterparts(db: Session, household: Household, src: SourceRecord, cfg: dict) -> list[SourceRecord]:
    window = max(cfg["date_window_days"], cfg["refund_window_days"])
    other = aliased(SourceRecord)
    refs = list(_refs(src))
    date_cond = and_(other.occurred_on >= src.occurred_on - timedelta(days=window), other.occurred_on <= src.occurred_on + timedelta(days=window))
    conds = [date_cond]
    if refs:
        conds.append(or_(other.upi_txn_id.in_(refs), other.utr.in_(refs), other.bank_ref.in_(refs)))
    if src.invoice_number:
        conds.append(other.invoice_number == src.invoice_number)
    q = (
        select(other)
        .join(CanonicalTransaction, CanonicalTransaction.id == other.canonical_transaction_id)
        .where(
            other.household_id == src.household_id,
            other.id != src.id,
            other.status == "active",
            other.canonical_transaction_id == other.original_transaction_id,
            other.canonical_transaction_id != src.canonical_transaction_id,
            CanonicalTransaction.status == "active",
            or_(*conds),
        )
        .limit(500)
    )
    return list(db.scalars(q).all())


def upsert_match(db: Session, household: Household, sc: Score, cfg: dict) -> ReconciliationMatch | None:
    conf = confidence_for(cfg, sc.score, sc.conflict)
    lo, hi = sorted([sc.a.id, sc.b.id], key=str)
    existing = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.household_id == household.id,
            ReconciliationMatch.kind == sc.kind,
            or_(
                and_(ReconciliationMatch.a_source_id == sc.a.id, ReconciliationMatch.b_source_id == sc.b.id),
                and_(ReconciliationMatch.a_source_id == sc.b.id, ReconciliationMatch.b_source_id == sc.a.id),
            ),
        )
    ).first()
    if existing is not None:
        if existing.status != "suggested":
            return existing  # never override a user's confirm / reject / unlink decision
        if conf is None:
            db.delete(existing)  # evidence changed (e.g. payment now fully linked elsewhere)
            return None
        _apply(existing, sc, conf)
        return existing
    if conf is None:
        return None
    m = ReconciliationMatch(id=uuid.uuid4(), household_id=household.id, kind=sc.kind, a_source_id=sc.a.id, b_source_id=sc.b.id, status="suggested", origin="engine")
    _apply(m, sc, conf)
    try:
        with db.begin_nested():
            db.add(m)
    except IntegrityError:
        # A concurrent worker created the same pair; theirs wins.
        return None
    return m


def _apply(m: ReconciliationMatch, sc: Score, conf: str) -> None:
    m.score = sc.score
    m.confidence = conf
    m.reasons = sc.reasons
    m.conflict = sc.conflict
    m.amount_difference = abs(sc.amount_difference)
    m.date_difference_days = sc.date_difference_days
    m.merchant_similarity = Decimal(str(sc.merchant_similarity))
    m.suggested_amount = sc.suggested_amount


def generate_candidates(db: Session, household: Household, src: SourceRecord) -> list[ReconciliationMatch]:
    """Score `src` against plausible counterparts and upsert suggestions. Returns the affected matches."""
    if not _eligible(db, src):
        return []
    cfg = matching_config(household)
    out = []
    for other in find_counterparts(db, household, src, cfg):
        pair = classify_pair(db, src, other)
        if pair is None:
            continue
        kind, a, b = pair
        sc = score_pair(db, household, kind, a, b, cfg)
        if sc is None:
            _drop_stale(db, household, kind, a, b)
            continue
        m = upsert_match(db, household, sc, cfg)
        if m is not None:
            out.append(m)
    db.flush()
    return out


def _drop_stale(db: Session, household: Household, kind: str, a: SourceRecord, b: SourceRecord) -> None:
    stale = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.household_id == household.id,
            ReconciliationMatch.kind == kind,
            ReconciliationMatch.status == "suggested",
            or_(
                and_(ReconciliationMatch.a_source_id == a.id, ReconciliationMatch.b_source_id == b.id),
                and_(ReconciliationMatch.a_source_id == b.id, ReconciliationMatch.b_source_id == a.id),
            ),
        )
    ).all()
    for m in stale:
        db.delete(m)


def explain_pair(db: Session, household: Household, x: SourceRecord, y: SourceRecord) -> Score | None:
    pair = classify_pair(db, x, y)
    if pair is None:
        return None
    kind, a, b = pair
    return score_pair(db, household, kind, a, b)

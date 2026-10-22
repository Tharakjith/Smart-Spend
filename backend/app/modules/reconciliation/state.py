"""Derives allocation totals, reconciliation statuses and counted amounts from the allocation graph.

Every function here is deterministic and recomputes from scratch, so running it twice is harmless and
`recalculate` can rebuild any drift.
"""
import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import CanonicalTransaction, ReconciliationAllocation, ReconciliationMatch, SourceRecord

ZERO = Decimal("0")

CT_STATUS_PRIORITY = [
    "needs_review",
    "disputed",
    "partially_paid",
    "partially_reconciled",
    "suggested_match",
    "fully_paid",
    "matched",
    "unmatched",
]


def _allocated(db: Session, source: SourceRecord) -> Decimal:
    col = ReconciliationAllocation.payment_source_id if source.role == "payment" else ReconciliationAllocation.bill_source_id
    total = db.scalar(select(func.coalesce(func.sum(ReconciliationAllocation.amount), 0)).where(col == source.id, ReconciliationAllocation.status == "active"))
    return Decimal(total or 0)


def recompute_source(db: Session, src: SourceRecord) -> None:
    src.allocated_amount = _allocated(db, src)
    ct = db.get(CanonicalTransaction, src.canonical_transaction_id)
    open_matches = db.execute(
        select(ReconciliationMatch.status, ReconciliationMatch.conflict, ReconciliationMatch.kind, ReconciliationMatch.confidence).where(
            or_(ReconciliationMatch.a_source_id == src.id, ReconciliationMatch.b_source_id == src.id),
            ReconciliationMatch.status.in_(("suggested", "confirmed")),
        )
    ).all()
    has_conflict = any(st == "suggested" and conflict for st, conflict, _, _ in open_matches)
    # Low-confidence candidates sit in the review queue only; they do not flag the record as "suggested".
    has_suggestion = any(st == "suggested" and conf != "low" for st, _, _, conf in open_matches)
    confirmed_dup_or_refund = any(st == "confirmed" and kind in ("duplicate", "refund") for st, _, kind, _ in open_matches)

    if src.status == "reversed" or (ct and ct.status == "reversed"):
        status = "reversed"
    elif ct and ct.review_status == "disputed":
        status = "disputed"
    elif has_conflict:
        status = "needs_review"
    elif src.canonical_transaction_id != src.original_transaction_id or confirmed_dup_or_refund:
        status = "matched"
    else:
        alloc = src.allocated_amount
        if alloc <= 0:
            status = "suggested_match" if has_suggestion else "unmatched"
        elif alloc < src.amount:
            status = "partially_paid" if src.role == "bill" else "partially_reconciled"
        else:
            status = "fully_paid" if src.role == "bill" else "matched"
    src.reconciliation_status = status


def recompute_transaction(db: Session, ct: CanonicalTransaction) -> None:
    sources = db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id == ct.id)).all()
    for s in sources:
        recompute_source(db, s)
    amount = Decimal(ct.amount)
    if ct.status != "active":
        ct.effective_amount = ZERO
        ct.cash_amount = ZERO
        ct.reconciliation_status = "reversed" if ct.status == "reversed" else "matched" if ct.status == "merged" else ct.reconciliation_status
        return
    payments = [s for s in sources if s.role == "payment" and s.status == "active"]
    bills = [s for s in sources if s.role == "bill" and s.status == "active"]
    # Portion of this payment that settles bills elsewhere is counted through those bills instead.
    absorbed = min(amount, sum((s.allocated_amount for s in payments), ZERO))
    ct.effective_amount = amount - absorbed
    if payments:
        ct.cash_amount = amount
    else:
        bill_paid = sum((s.allocated_amount for s in bills), ZERO)
        ct.cash_amount = ZERO if bill_paid > 0 else amount
    if ct.review_status == "disputed":
        ct.reconciliation_status = "disputed"
        return
    statuses = {s.reconciliation_status for s in sources} or {"unmatched"}
    for st in CT_STATUS_PRIORITY:
        if st in statuses:
            ct.reconciliation_status = st
            break


def recompute_for_sources(db: Session, source_ids: list[uuid.UUID]) -> None:
    ct_ids = set()
    for sid in source_ids:
        s = db.get(SourceRecord, sid)
        if s is not None:
            ct_ids.add(s.canonical_transaction_id)
            ct_ids.add(s.original_transaction_id)
    db.flush()
    for cid in ct_ids:
        ct = db.get(CanonicalTransaction, cid)
        if ct is not None:
            recompute_transaction(db, ct)
    db.flush()


def bill_settlement(db: Session, ct: CanonicalTransaction) -> dict | None:
    bills = db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id == ct.id, SourceRecord.role == "bill", SourceRecord.status == "active")).all()
    if not bills:
        return None
    total = sum((Decimal(b.amount) for b in bills if b.canonical_transaction_id == b.original_transaction_id), ZERO) or Decimal(ct.amount)
    paid = sum((Decimal(b.allocated_amount) for b in bills), ZERO)
    paid = min(paid, total)
    if paid <= 0:
        state = "unpaid_or_direct"
    elif paid < total:
        state = "partially_paid"
    else:
        state = "fully_paid"
    return {"bill_total": total, "paid_amount": paid, "remaining_amount": total - paid, "settlement_status": state}

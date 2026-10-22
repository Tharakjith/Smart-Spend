"""User-driven reconciliation actions. Each runs in one DB transaction with row locks taken in a fixed order,
validates against freshly-read allocation sums, writes an audit entry, and recomputes counted amounts."""
import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.db import utcnow
from app.core.deps import Ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import fmt, quantize
from app.models import (
    CanonicalTransaction,
    ReconciliationAllocation,
    ReconciliationAuditLog,
    ReconciliationMatch,
    SourceRecord,
)
from app.modules.common import snapshot
from app.modules.merchants.service import add_alias
from app.modules.reconciliation import engine
from app.modules.reconciliation.state import recompute_for_sources

ZERO = Decimal("0")


def _log(ctx: Ctx, action: str, match: ReconciliationMatch | None = None, allocation: ReconciliationAllocation | None = None, before=None, after=None, note: str = ""):
    ctx.db.add(
        ReconciliationAuditLog(
            household_id=ctx.household_id,
            match_id=match.id if match else None,
            allocation_id=allocation.id if allocation else None,
            action=action,
            actor_id=ctx.user.id,
            before=before,
            after=after,
            note=note,
        )
    )


def lock_sources(ctx: Ctx, ids) -> dict[uuid.UUID, SourceRecord]:
    """SELECT ... FOR UPDATE in ascending id order (prevents deadlocks between concurrent reconcilers)."""
    ids = sorted(set(ids), key=str)
    rows = ctx.db.scalars(select(SourceRecord).where(SourceRecord.id.in_(ids)).order_by(SourceRecord.id).with_for_update()).all()
    found = {r.id: r for r in rows}
    for i in ids:
        if i not in found or found[i].household_id != ctx.household_id:
            raise NotFound("Source record not found")
    for r in rows:
        ctx.db.refresh(r)  # re-read under the lock
    return found


def _lock_match(ctx: Ctx, match_id: uuid.UUID) -> ReconciliationMatch:
    m = ctx.db.scalars(select(ReconciliationMatch).where(ReconciliationMatch.id == match_id).with_for_update()).first()
    if m is None or m.household_id != ctx.household_id:
        raise NotFound("Reconciliation match not found")
    ctx.db.refresh(m)
    return m


def _active_sum(ctx: Ctx, col, source_id) -> Decimal:
    return Decimal(
        ctx.db.scalar(select(func.coalesce(func.sum(ReconciliationAllocation.amount), 0)).where(col == source_id, ReconciliationAllocation.status == "active")) or 0
    )


def _require_usable(src: SourceRecord, label: str) -> None:
    if src.status != "active":
        raise Conflict(f"The {label} record is {src.status}", code="source_inactive")
    if src.canonical_transaction_id != src.original_transaction_id:
        raise Conflict(f"The {label} record is merged into another transaction as a duplicate; use the primary record", code="source_merged")


def create_allocation(ctx: Ctx, payment: SourceRecord, bill: SourceRecord, amount: Decimal, match: ReconciliationMatch | None) -> ReconciliationAllocation:
    """Caller must hold locks on both sources."""
    _require_usable(payment, "payment")
    _require_usable(bill, "bill")
    if payment.role != "payment" or payment.direction != "out":
        raise ValidationFailed("Only outgoing payment records can be allocated", code="not_a_payment")
    if bill.role != "bill":
        raise ValidationFailed("Payments can only be allocated to bill/receipt records", code="not_a_bill")
    if payment.currency != bill.currency:
        raise ValidationFailed("Payment and bill currencies differ", code="currency_mismatch")
    amount = quantize(amount, payment.currency)
    if amount <= 0:
        raise ValidationFailed("Allocation amount must be greater than zero", code="allocation_not_positive")
    pay_avail = Decimal(payment.amount) - _active_sum(ctx, ReconciliationAllocation.payment_source_id, payment.id)
    bill_remaining = Decimal(bill.amount) - _active_sum(ctx, ReconciliationAllocation.bill_source_id, bill.id)
    if amount > pay_avail:
        raise Conflict(
            f"Allocation {fmt(amount, payment.currency)} exceeds the payment's unallocated balance {fmt(pay_avail, payment.currency)}",
            code="allocation_exceeds_payment",
            details={"available": format(pay_avail, "f")},
        )
    if amount > bill_remaining:
        raise Conflict(
            f"Allocation {fmt(amount, bill.currency)} exceeds the bill's remaining balance {fmt(bill_remaining, bill.currency)}",
            code="allocation_exceeds_bill",
            details={"remaining": format(bill_remaining, "f")},
        )
    existing = ctx.db.scalars(
        select(ReconciliationAllocation).where(
            ReconciliationAllocation.payment_source_id == payment.id,
            ReconciliationAllocation.bill_source_id == bill.id,
            ReconciliationAllocation.status == "active",
        )
    ).first()
    if existing:
        # Top up the existing link rather than creating a parallel allocation for the same pair.
        before = {"amount": format(existing.amount, "f")}
        existing.amount = Decimal(existing.amount) + amount
        _log(ctx, "allocation_increased", match, existing, before, {"amount": format(existing.amount, "f")})
        return existing
    alloc = ReconciliationAllocation(
        household_id=ctx.household_id, match_id=match.id if match else None, payment_source_id=payment.id, bill_source_id=bill.id, amount=amount, created_by=ctx.user.id
    )
    try:
        with ctx.db.begin_nested():
            ctx.db.add(alloc)
    except IntegrityError:
        raise Conflict("This payment is already allocated to this bill", code="duplicate_allocation")
    _log(ctx, "allocation_created", match, alloc, None, {"payment_source_id": str(payment.id), "bill_source_id": str(bill.id), "amount": format(amount, "f")})
    return alloc


def _learn_alias(ctx: Ctx, a: SourceRecord, b: SourceRecord) -> None:
    """Confirmed matches teach merchant aliases (e.g. 'FRESHMART TRIVANDRUM' -> 'Fresh Mart Supermarket')."""
    target = a.merchant_id or b.merchant_id
    if not target:
        return
    for s in (a, b):
        if s.merchant_raw and s.merchant_id != target:
            add_alias(ctx.db, ctx.household_id, target, s.merchant_raw, "confirmed_match")


def confirm_match(ctx: Ctx, match_id: uuid.UUID, amount: Decimal | None = None, note: str = "", as_reversal: bool = False) -> ReconciliationMatch:
    m = _lock_match(ctx, match_id)
    if m.status == "confirmed":
        return m  # idempotent
    if m.status != "suggested":
        raise Conflict(f"Only suggested matches can be confirmed (this one is {m.status}). Reopen it first.", code="match_not_suggested")
    srcs = lock_sources(ctx, [m.a_source_id, m.b_source_id])
    a, b = srcs[m.a_source_id], srcs[m.b_source_id]
    before = snapshot(m, ["status", "score", "confidence"])
    after_extra: dict = {}
    if m.kind == "bill_payment":
        if amount is None:
            avail = Decimal(b.amount) - Decimal(b.allocated_amount)
            remaining = Decimal(a.amount) - Decimal(a.allocated_amount)
            amount = m.suggested_amount if m.suggested_amount and m.suggested_amount <= min(avail, remaining) else min(avail, remaining)
        alloc = create_allocation(ctx, payment=b, bill=a, amount=amount, match=m)
        after_extra["allocation_id"] = str(alloc.id)
        after_extra["amount"] = format(Decimal(amount), "f")
        # The bill now carries the counted amount; let it report how it was paid (reverted on unlink).
        bill_ct = ctx.db.get(CanonicalTransaction, a.canonical_transaction_id)
        pay_ct = ctx.db.get(CanonicalTransaction, b.canonical_transaction_id)
        if bill_ct.payment_method is None and pay_ct.payment_method is not None:
            bill_ct.payment_method = pay_ct.payment_method
            after_extra["filled_fields"] = {"payment_method": pay_ct.payment_method}
    elif m.kind == "duplicate":
        _require_usable(a, "primary")
        _require_usable(b, "duplicate")
        if Decimal(b.allocated_amount) > 0:
            raise Conflict("The duplicate record has allocations. Unlink them before merging.", code="duplicate_has_allocations")
        primary = ctx.db.get(CanonicalTransaction, a.canonical_transaction_id)
        secondary = ctx.db.get(CanonicalTransaction, b.canonical_transaction_id)
        if Decimal(primary.amount) != Decimal(secondary.amount) and amount is None:
            after_extra["amount_note"] = "Amounts differ; primary amount kept"
        filled = {}
        for f in ("account_id", "to_account_id", "payment_method", "merchant_id", "counterparty_id"):
            if getattr(primary, f) is None and getattr(secondary, f) is not None:
                setattr(primary, f, getattr(secondary, f))
                filled[f] = str(getattr(secondary, f))
        secondary.status = "merged"
        secondary.merged_into_id = primary.id
        secondary.version += 1
        b.canonical_transaction_id = primary.id
        after_extra.update({"merged_transaction_id": str(secondary.id), "into_transaction_id": str(primary.id), "filled_fields": filled})
    elif m.kind == "refund":
        original = ctx.db.get(CanonicalTransaction, a.canonical_transaction_id)
        refund = ctx.db.get(CanonicalTransaction, b.canonical_transaction_id)
        after_extra.update({"previous_refund_type": refund.type, "as_reversal": as_reversal})
        refund.related_transaction_id = original.id
        if as_reversal:
            if Decimal(refund.amount) != Decimal(original.amount):
                raise ValidationFailed("A reversal must be for the full original amount; use a refund for partial credits")
            if Decimal(a.allocated_amount) > 0:
                raise Conflict("Unlink this payment from its bills before marking it reversed", code="has_allocations")
            original.status = "reversed"
            refund.status = "reversed"
            a.status = "reversed"
            b.status = "reversed"
        else:
            refund.type = "refund"
        refund.version += 1
        original.version += 1
    _learn_alias(ctx, a, b)
    m.status = "confirmed"
    m.decided_by = ctx.user.id
    m.decided_at = utcnow()
    m.note = note or m.note
    ctx.db.flush()
    _log(ctx, "confirmed", m, None, before, {**snapshot(m, ["status", "score", "confidence"]), **after_extra}, note)
    _refresh_after_change(ctx, [a, b])
    ctx.db.commit()
    return m


def _refresh_after_change(ctx: Ctx, sources: list[SourceRecord]) -> None:
    """Recompute counted amounts, then re-score other suggestions that involve these records."""
    ids = [s.id for s in sources]
    recompute_for_sources(ctx.db, ids)
    for s in sources:
        engine.generate_candidates(ctx.db, ctx.household, s)
    related = ctx.db.execute(
        select(ReconciliationMatch.a_source_id, ReconciliationMatch.b_source_id).where(or_(ReconciliationMatch.a_source_id.in_(ids), ReconciliationMatch.b_source_id.in_(ids)))
    ).all()
    recompute_for_sources(ctx.db, list({x for r in related for x in r} | set(ids)))


def reject_match(ctx: Ctx, match_id: uuid.UUID, note: str = "", separate: bool = False) -> ReconciliationMatch:
    m = _lock_match(ctx, match_id)
    if m.status == "rejected":
        return m
    if m.status == "confirmed":
        raise Conflict("Confirmed matches must be unlinked, not rejected", code="match_confirmed")
    before = snapshot(m, ["status"])
    m.status = "rejected"
    m.decided_by = ctx.user.id
    m.decided_at = utcnow()
    m.note = note or ("Marked as separate purchases" if separate else "Rejected")
    _log(ctx, "rejected", m, None, before, {"status": "rejected", "separate_purchases": separate}, m.note)
    ctx.db.flush()
    recompute_for_sources(ctx.db, [m.a_source_id, m.b_source_id])
    ctx.db.commit()
    return m


def _undo_match(ctx: Ctx, m: ReconciliationMatch, a: SourceRecord, b: SourceRecord) -> dict:
    undone: dict = {}
    if m.kind == "bill_payment":
        allocs = ctx.db.scalars(select(ReconciliationAllocation).where(ReconciliationAllocation.match_id == m.id, ReconciliationAllocation.status == "active")).all()
        allocs += ctx.db.scalars(
            select(ReconciliationAllocation).where(
                ReconciliationAllocation.payment_source_id == b.id, ReconciliationAllocation.bill_source_id == a.id, ReconciliationAllocation.status == "active"
            )
        ).all()
        for al in {x.id: x for x in allocs}.values():
            al.status = "removed"
            al.removed_by = ctx.user.id
            al.removed_at = utcnow()
            _log(ctx, "allocation_removed", m, al, {"amount": format(al.amount, "f")}, None)
        undone["allocations_removed"] = len(allocs)
        last = ctx.db.scalars(
            select(ReconciliationAuditLog).where(ReconciliationAuditLog.match_id == m.id, ReconciliationAuditLog.action == "confirmed").order_by(ReconciliationAuditLog.created_at.desc())
        ).first()
        filled = ((last.after or {}).get("filled_fields") or {}) if last else {}
        bill_ct = ctx.db.get(CanonicalTransaction, a.canonical_transaction_id)
        if "payment_method" in filled and bill_ct.payment_method == filled["payment_method"]:
            bill_ct.payment_method = None
    elif m.kind == "duplicate":
        secondary = ctx.db.get(CanonicalTransaction, b.original_transaction_id)
        if secondary.status == "merged":
            secondary.status = "active"
            secondary.merged_into_id = None
            secondary.version += 1
        b.canonical_transaction_id = b.original_transaction_id
        # Revert fields copied onto the primary at merge time.
        last = ctx.db.scalars(
            select(ReconciliationAuditLog).where(ReconciliationAuditLog.match_id == m.id, ReconciliationAuditLog.action == "confirmed").order_by(ReconciliationAuditLog.created_at.desc())
        ).first()
        filled = ((last.after or {}).get("filled_fields") or {}) if last else {}
        primary = ctx.db.get(CanonicalTransaction, a.canonical_transaction_id)
        for f, v in filled.items():
            if str(getattr(primary, f)) == v:
                setattr(primary, f, None)
        undone["unmerged_transaction_id"] = str(secondary.id)
    elif m.kind == "refund":
        original = ctx.db.get(CanonicalTransaction, a.original_transaction_id)
        refund = ctx.db.get(CanonicalTransaction, b.original_transaction_id)
        last = ctx.db.scalars(
            select(ReconciliationAuditLog).where(ReconciliationAuditLog.match_id == m.id, ReconciliationAuditLog.action == "confirmed").order_by(ReconciliationAuditLog.created_at.desc())
        ).first()
        prev_type = ((last.after or {}).get("previous_refund_type")) if last else None
        refund.related_transaction_id = None
        if original.status == "reversed":
            original.status = "active"
            a.status = "active"
        if refund.status == "reversed":
            refund.status = "active"
            b.status = "active"
        if prev_type:
            refund.type = prev_type
        undone["refund_unlinked"] = True
    return undone


def unlink(ctx: Ctx, match_id: uuid.UUID | None = None, allocation_id: uuid.UUID | None = None, note: str = "") -> dict:
    if allocation_id and not match_id:
        al = ctx.db.scalars(select(ReconciliationAllocation).where(ReconciliationAllocation.id == allocation_id).with_for_update()).first()
        if al is None or al.household_id != ctx.household_id:
            raise NotFound("Allocation not found")
        srcs = lock_sources(ctx, [al.payment_source_id, al.bill_source_id])
        if al.status != "active":
            return {"ok": True, "already_removed": True}
        al.status = "removed"
        al.removed_by = ctx.user.id
        al.removed_at = utcnow()
        m = ctx.db.get(ReconciliationMatch, al.match_id) if al.match_id else None
        _log(ctx, "allocation_removed", m, al, {"amount": format(al.amount, "f")}, None, note)
        ctx.db.flush()
        if m is not None and m.status == "confirmed":
            remaining = ctx.db.scalar(select(func.count()).select_from(ReconciliationAllocation).where(ReconciliationAllocation.match_id == m.id, ReconciliationAllocation.status == "active"))
            if not remaining:
                m.status = "unlinked"
                m.decided_by = ctx.user.id
                m.decided_at = utcnow()
        _refresh_after_change(ctx, list(srcs.values()))
        ctx.db.commit()
        return {"ok": True}
    if not match_id:
        raise ValidationFailed("Provide match_id or allocation_id")
    m = _lock_match(ctx, match_id)
    if m.status != "confirmed":
        raise Conflict(f"Only confirmed matches can be unlinked (this one is {m.status})", code="match_not_confirmed")
    srcs = lock_sources(ctx, [m.a_source_id, m.b_source_id])
    a, b = srcs[m.a_source_id], srcs[m.b_source_id]
    undone = _undo_match(ctx, m, a, b)
    m.status = "unlinked"
    m.decided_by = ctx.user.id
    m.decided_at = utcnow()
    _log(ctx, "unlinked", m, None, {"status": "confirmed"}, {"status": "unlinked", **undone}, note)
    ctx.db.flush()
    _refresh_after_change(ctx, [a, b])
    ctx.db.commit()
    return {"ok": True, **undone}


def reopen(ctx: Ctx, match_id: uuid.UUID, note: str = "") -> ReconciliationMatch:
    m = _lock_match(ctx, match_id)
    if m.status == "suggested":
        return m
    srcs = lock_sources(ctx, [m.a_source_id, m.b_source_id])
    a, b = srcs[m.a_source_id], srcs[m.b_source_id]
    prev = m.status
    if prev == "confirmed":
        _undo_match(ctx, m, a, b)
    m.status = "suggested"
    m.decided_by = ctx.user.id
    m.decided_at = utcnow()
    sc = engine.score_pair(ctx.db, ctx.household, m.kind, a, b)
    if sc is not None:
        engine._apply(m, sc, engine.confidence_for(engine.matching_config(ctx.household), sc.score, sc.conflict) or "low")
    _log(ctx, "reopened", m, None, {"status": prev}, {"status": "suggested"}, note)
    ctx.db.flush()
    recompute_for_sources(ctx.db, [a.id, b.id])
    ctx.db.commit()
    return m


def resolve_source(ctx: Ctx, source_id: uuid.UUID | None, transaction_id: uuid.UUID | None, role: str | None = None) -> SourceRecord:
    if source_id:
        s = ctx.db.get(SourceRecord, source_id)
    elif transaction_id:
        q = select(SourceRecord).where(
            SourceRecord.canonical_transaction_id == transaction_id,
            SourceRecord.original_transaction_id == transaction_id,
            SourceRecord.household_id == ctx.household_id,
        )
        if role:
            q = q.where(SourceRecord.role == role)
        s = ctx.db.scalars(q.order_by(SourceRecord.created_at)).first()
    else:
        raise ValidationFailed("Provide a source id or a transaction id")
    if s is None or s.household_id != ctx.household_id:
        raise NotFound("Record not found" + (f" (no {role} record on that transaction)" if role else ""))
    return s


def manual_match(ctx: Ctx, x: SourceRecord, y: SourceRecord, amount: Decimal | None, note: str, kind: str | None = None, as_reversal: bool = False) -> ReconciliationMatch:
    if x.id == y.id or x.canonical_transaction_id == y.canonical_transaction_id:
        raise ValidationFailed("Pick two different records")
    pair = engine.classify_pair(ctx.db, x, y)
    if pair is None:
        raise ValidationFailed(
            "These records cannot describe the same event (check roles, directions and transaction types: a bill pairs with an outgoing payment; duplicates share role and type).",
            code="incompatible_records",
        )
    k, a, b = pair
    if kind and kind != k:
        raise ValidationFailed(f"These records form a '{k}' relationship, not '{kind}'")
    if k == "refund":
        if Decimal(b.amount) > Decimal(a.amount):
            raise ValidationFailed("A refund can't be larger than the original payment", code="refund_exceeds_original")
        if b.occurred_on < a.occurred_on:
            raise ValidationFailed("A refund can't be dated before the original payment", code="refund_before_original")
    existing = ctx.db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.household_id == ctx.household_id,
            ReconciliationMatch.kind == k,
            or_(
                (ReconciliationMatch.a_source_id == a.id) & (ReconciliationMatch.b_source_id == b.id),
                (ReconciliationMatch.a_source_id == b.id) & (ReconciliationMatch.b_source_id == a.id),
            ),
        )
    ).first()
    sc = engine.score_pair(ctx.db, ctx.household, k, a, b)
    if existing is None:
        existing = ReconciliationMatch(household_id=ctx.household_id, kind=k, a_source_id=a.id, b_source_id=b.id, origin="manual", status="suggested", score=0, confidence="low")
        ctx.db.add(existing)
    if existing.status == "confirmed" and k != "bill_payment":
        return existing
    if sc is not None:
        engine._apply(existing, sc, engine.confidence_for(engine.matching_config(ctx.household), sc.score, sc.conflict) or "low")
    else:
        existing.score = 0
        existing.confidence = "low"
        existing.reasons = [{"code": "manual", "points": 0, "text": "Linked manually by a user; automatic evidence was insufficient"}]
    existing.origin = "manual" if existing.status != "suggested" or existing.origin == "manual" else existing.origin
    if existing.status == "confirmed":
        # Additional allocation on an already-confirmed bill/payment pair.
        lock_sources(ctx, [a.id, b.id])
        create_allocation(ctx, payment=b, bill=a, amount=amount or (Decimal(b.amount) - Decimal(b.allocated_amount)), match=existing)
        ctx.db.flush()
        _refresh_after_change(ctx, [a, b])
        ctx.db.commit()
        return existing
    existing.status = "suggested"
    ctx.db.flush()
    _log(ctx, "manual_match", existing, None, None, {"a": str(a.id), "b": str(b.id), "kind": k}, note)
    ctx.db.flush()
    return confirm_match(ctx, existing.id, amount=amount, note=note or "Manual match", as_reversal=as_reversal)


def allocate_payment(ctx: Ctx, payment: SourceRecord, allocations: list[tuple[SourceRecord, Decimal]], note: str = "") -> list[ReconciliationAllocation]:
    """Splits one payment across several bills atomically (Scenario E)."""
    if not allocations:
        raise ValidationFailed("Provide at least one allocation")
    bills = [b for b, _ in allocations]
    if len({b.id for b in bills}) != len(bills):
        raise ValidationFailed("Each bill may appear only once per request")
    locked = lock_sources(ctx, [payment.id] + [b.id for b in bills])
    payment = locked[payment.id]
    total = sum((quantize(a, payment.currency) for _, a in allocations), ZERO)
    available = Decimal(payment.amount) - _active_sum(ctx, ReconciliationAllocation.payment_source_id, payment.id)
    if total > available:
        raise Conflict(
            f"Total allocation {fmt(total, payment.currency)} exceeds the payment's unallocated balance {fmt(available, payment.currency)}",
            code="allocation_exceeds_payment",
            details={"available": format(available, "f"), "requested": format(total, "f")},
        )
    created = []
    for bill, amt in allocations:
        bill = locked[bill.id]
        if engine.classify_pair(ctx.db, bill, payment) is None or bill.role != "bill":
            raise ValidationFailed(f"Record {bill.id} is not a bill that this payment can settle", code="incompatible_records")
        m = ctx.db.scalars(
            select(ReconciliationMatch).where(
                ReconciliationMatch.household_id == ctx.household_id,
                ReconciliationMatch.kind == "bill_payment",
                ReconciliationMatch.a_source_id == bill.id,
                ReconciliationMatch.b_source_id == payment.id,
            )
        ).first()
        if m is None:
            sc = engine.score_pair(ctx.db, ctx.household, "bill_payment", bill, payment)
            m = ReconciliationMatch(
                household_id=ctx.household_id, kind="bill_payment", a_source_id=bill.id, b_source_id=payment.id, origin="manual", status="confirmed", score=sc.score if sc else 0, confidence="low"
            )
            if sc:
                engine._apply(m, sc, engine.confidence_for(engine.matching_config(ctx.household), sc.score, sc.conflict) or "low")
            ctx.db.add(m)
            ctx.db.flush()
        m.status = "confirmed"
        m.decided_by = ctx.user.id
        m.decided_at = utcnow()
        created.append(create_allocation(ctx, payment=payment, bill=bill, amount=amt, match=m))
        ctx.db.flush()
    _refresh_after_change(ctx, [payment] + [locked[b.id] for b in bills])
    ctx.db.commit()
    return created


def recalculate(ctx: Ctx, regenerate: bool = True) -> dict:
    """Rebuild counted amounts and statuses from the allocation graph; optionally regenerate suggestions."""
    cts = ctx.db.scalars(select(CanonicalTransaction).where(CanonicalTransaction.household_id == ctx.household_id)).all()
    before = {c.id: (Decimal(c.effective_amount), Decimal(c.cash_amount), c.reconciliation_status) for c in cts}
    from app.modules.reconciliation.state import recompute_transaction

    for c in cts:
        recompute_transaction(ctx.db, c)
    ctx.db.flush()
    created = 0
    if regenerate:
        sources = ctx.db.scalars(select(SourceRecord).where(SourceRecord.household_id == ctx.household_id, SourceRecord.status == "active")).all()
        for s in sources:
            created += len(engine.generate_candidates(ctx.db, ctx.household, s))
        for c in cts:
            recompute_transaction(ctx.db, c)
    drift = [str(c.id) for c in cts if before[c.id][:2] != (Decimal(c.effective_amount), Decimal(c.cash_amount))]
    _log(ctx, "recalculated", None, None, None, {"transactions": len(cts), "drift_corrected": len(drift)})
    ctx.db.commit()
    return {"transactions_recomputed": len(cts), "amount_drift_corrected": drift, "suggestions_touched": created}

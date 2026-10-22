import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import Field, model_validator
from sqlalchemy import and_, func, or_, select

from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.errors import NotFound, ValidationFailed
from app.core.idempotency import run_idempotent
from app.core.money import quantize
from app.models import (
    CanonicalTransaction,
    Document,
    DuplicateCandidate,
    ReconciliationAllocation,
    ReconciliationAuditLog,
    ReconciliationMatch,
    SourceRecord,
)
from app.modules.common import Money, OptMoney, Schema
from app.modules.ledger.service import serialize_allocation, serialize_source
from app.modules.reconciliation import service

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


class ConfirmIn(Schema):
    amount: OptMoney = None
    note: str = Field(default="", max_length=500)
    as_reversal: bool = False


class RejectIn(Schema):
    note: str = Field(default="", max_length=500)
    separate_purchases: bool = False


class ManualMatchIn(Schema):
    a_source_id: uuid.UUID | None = None
    a_transaction_id: uuid.UUID | None = None
    b_source_id: uuid.UUID | None = None
    b_transaction_id: uuid.UUID | None = None
    kind: str | None = Field(default=None, pattern="^(bill_payment|duplicate|refund)$")
    amount: OptMoney = None
    note: str = Field(default="", max_length=500)
    as_reversal: bool = False

    @model_validator(mode="after")
    def _ids(self):
        if not (self.a_source_id or self.a_transaction_id) or not (self.b_source_id or self.b_transaction_id):
            raise ValueError("Provide both records (source id or transaction id)")
        return self


class AllocationItem(Schema):
    bill_source_id: uuid.UUID | None = None
    bill_transaction_id: uuid.UUID | None = None
    amount: Money


class AllocateIn(Schema):
    payment_source_id: uuid.UUID | None = None
    payment_transaction_id: uuid.UUID | None = None
    allocations: list[AllocationItem] = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=500)


class UnlinkIn(Schema):
    match_id: uuid.UUID | None = None
    allocation_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=500)


class BulkConfirmIn(Schema):
    match_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    confirm: bool = Field(description="Must be true: explicit acknowledgement that each match will be linked")


def _tx_brief(db, tx_id) -> dict | None:
    ct = db.get(CanonicalTransaction, tx_id)
    if ct is None:
        return None
    return {
        "id": str(ct.id),
        "type": ct.type,
        "description": ct.description,
        "amount": format(Decimal(ct.amount), "f"),
        "effective_amount": format(Decimal(ct.effective_amount), "f"),
        "status": ct.status,
        "reconciliation_status": ct.reconciliation_status,
        "category_id": str(ct.category_id) if ct.category_id else None,
    }


def _source_detail(db, s: SourceRecord) -> dict:
    out = serialize_source(s)
    out["transaction"] = _tx_brief(db, s.canonical_transaction_id)
    if s.document_id:
        d = db.get(Document, s.document_id)
        out["document"] = {"id": str(d.id), "filename": d.original_filename, "status": d.status} if d else None
    return out


def serialize_match(db, m: ReconciliationMatch, detail: bool = False) -> dict:
    a = db.get(SourceRecord, m.a_source_id)
    b = db.get(SourceRecord, m.b_source_id)
    labels = {"bill_payment": ("bill", "payment"), "duplicate": ("primary", "duplicate"), "refund": ("original", "refund")}[m.kind]
    actions = {
        "suggested": ["confirm", "reject", "mark_separate"] + (["adjust_amount"] if m.kind == "bill_payment" else []),
        "confirmed": ["unlink", "reopen"],
        "rejected": ["reopen"],
        "unlinked": ["reopen"],
    }[m.status]
    out = {
        "id": str(m.id),
        "kind": m.kind,
        "status": m.status,
        "origin": m.origin,
        "score": m.score,
        "confidence": m.confidence,
        "conflict": m.conflict,
        "reasons": m.reasons,
        "amount_difference": format(quantize(m.amount_difference, a.currency if a else "INR"), "f"),
        "date_difference_days": m.date_difference_days,
        "merchant_similarity": float(m.merchant_similarity),
        "suggested_amount": format(quantize(m.suggested_amount, a.currency if a else "INR"), "f") if m.suggested_amount is not None else None,
        "a_label": labels[0],
        "b_label": labels[1],
        "a": _source_detail(db, a) if a else None,
        "b": _source_detail(db, b) if b else None,
        "decided_by": str(m.decided_by) if m.decided_by else None,
        "decided_at": m.decided_at.isoformat() if m.decided_at else None,
        "note": m.note,
        "created_at": m.created_at.isoformat(),
        "available_actions": actions,
    }
    if detail:
        out["allocations"] = [serialize_allocation(db, al) for al in db.scalars(select(ReconciliationAllocation).where(ReconciliationAllocation.match_id == m.id)).all()]
        out["history"] = [
            {"action": h.action, "actor_id": str(h.actor_id) if h.actor_id else None, "at": h.created_at.isoformat(), "before": h.before, "after": h.after, "note": h.note}
            for h in db.scalars(select(ReconciliationAuditLog).where(ReconciliationAuditLog.match_id == m.id).order_by(ReconciliationAuditLog.created_at)).all()
        ]
    return out


@router.get("/candidates")
def candidates(
    ctx: Ctx = Depends(get_ctx),
    status: str = Query("suggested", pattern="^(suggested|confirmed|rejected|unlinked|all)$"),
    confidence: str | None = Query(None, pattern="^(high|medium|low)$"),
    kind: str | None = Query(None, pattern="^(bill_payment|duplicate|refund)$"),
    conflict: bool | None = None,
    transaction_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = Query(50, le=200),
):
    q = select(ReconciliationMatch).where(ReconciliationMatch.household_id == ctx.household_id)
    if status != "all":
        q = q.where(ReconciliationMatch.status == status)
    if confidence:
        q = q.where(ReconciliationMatch.confidence == confidence)
    if kind:
        q = q.where(ReconciliationMatch.kind == kind)
    if conflict is not None:
        q = q.where(ReconciliationMatch.conflict.is_(conflict))
    if transaction_id:
        src_ids = select(SourceRecord.id).where(or_(SourceRecord.canonical_transaction_id == transaction_id, SourceRecord.original_transaction_id == transaction_id))
        q = q.where(or_(ReconciliationMatch.a_source_id.in_(src_ids), ReconciliationMatch.b_source_id.in_(src_ids)))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(ReconciliationMatch.conflict.desc(), ReconciliationMatch.score.desc(), ReconciliationMatch.created_at.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize_match(ctx.db, m) for m in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/summary")
def summary(ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    hid = ctx.household_id
    by_conf = dict(
        db.execute(
            select(ReconciliationMatch.confidence, func.count()).where(ReconciliationMatch.household_id == hid, ReconciliationMatch.status == "suggested").group_by(ReconciliationMatch.confidence)
        ).all()
    )
    src_counts = dict(
        db.execute(
            select(SourceRecord.reconciliation_status, func.count())
            .where(SourceRecord.household_id == hid, SourceRecord.status == "active")
            .group_by(SourceRecord.reconciliation_status)
        ).all()
    )
    ct = CanonicalTransaction
    prevented = db.scalar(select(func.coalesce(func.sum(ct.amount - ct.effective_amount), 0)).where(ct.household_id == hid, ct.status == "active"))
    merged = db.scalar(select(func.coalesce(func.sum(ct.amount), 0)).where(ct.household_id == hid, ct.status == "merged"))
    unalloc = db.scalar(
        select(func.coalesce(func.sum(SourceRecord.amount - SourceRecord.allocated_amount), 0)).where(
            SourceRecord.household_id == hid, SourceRecord.status == "active", SourceRecord.reconciliation_status == "partially_reconciled"
        )
    )
    eligible = sum(src_counts.values())
    done = sum(src_counts.get(k, 0) for k in ("matched", "fully_paid", "reversed"))
    conflicts = db.scalar(select(func.count()).select_from(ReconciliationMatch).where(ReconciliationMatch.household_id == hid, ReconciliationMatch.status == "suggested", ReconciliationMatch.conflict.is_(True)))
    dup_uploads = db.scalar(select(func.count()).select_from(DuplicateCandidate).where(DuplicateCandidate.household_id == hid, DuplicateCandidate.status == "open"))
    return {
        "suggestions": {"high": by_conf.get("high", 0), "medium": by_conf.get("medium", 0), "low": by_conf.get("low", 0)},
        "source_status_counts": src_counts,
        "conflicts": conflicts,
        "duplicate_uploads_blocked": dup_uploads,
        "double_counting_prevented": format(quantize(Decimal(prevented or 0) + Decimal(merged or 0), ctx.household.base_currency), "f"),
        "unallocated_payment_balance": format(quantize(Decimal(unalloc or 0), ctx.household.base_currency), "f"),
        "completion_rate": round(done / eligible, 4) if eligible else 1.0,
        "currency": ctx.household.base_currency,
    }


@router.get("/queues")
def queues(ctx: Ctx = Depends(get_ctx), limit: int = Query(50, le=200)):
    """Everything the Duplicates & Reconciliation screen shows, grouped into review queues."""
    db = ctx.db
    hid = ctx.household_id

    def matches(*conds):
        rows = db.scalars(
            select(ReconciliationMatch).where(ReconciliationMatch.household_id == hid, *conds).order_by(ReconciliationMatch.score.desc(), ReconciliationMatch.created_at.desc()).limit(limit)
        ).all()
        return [serialize_match(db, m) for m in rows]

    def sources(*conds):
        rows = db.scalars(
            select(SourceRecord)
            .join(CanonicalTransaction, CanonicalTransaction.id == SourceRecord.canonical_transaction_id)
            .where(SourceRecord.household_id == hid, SourceRecord.status == "active", CanonicalTransaction.status == "active", SourceRecord.canonical_transaction_id == SourceRecord.original_transaction_id, *conds)
            .order_by(SourceRecord.occurred_on.desc())
            .limit(limit)
        ).all()
        return [_source_detail(db, s) for s in rows]

    dup_uploads = db.scalars(select(DuplicateCandidate).where(DuplicateCandidate.household_id == hid, DuplicateCandidate.status == "open").order_by(DuplicateCandidate.created_at.desc()).limit(limit)).all()
    overpaid = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.household_id == hid,
            ReconciliationMatch.kind == "bill_payment",
            ReconciliationMatch.status == "confirmed",
            ReconciliationMatch.amount_difference > 0,
        ).limit(limit)
    ).all()
    return {
        "suggested_bill_payments": matches(ReconciliationMatch.status == "suggested", ReconciliationMatch.kind == "bill_payment", ReconciliationMatch.conflict.is_(False)),
        "possible_duplicates": matches(ReconciliationMatch.status == "suggested", ReconciliationMatch.kind == "duplicate", ReconciliationMatch.conflict.is_(False)),
        "possible_refunds": matches(ReconciliationMatch.status == "suggested", ReconciliationMatch.kind == "refund", ReconciliationMatch.conflict.is_(False)),
        "conflicting_references": matches(ReconciliationMatch.status == "suggested", ReconciliationMatch.conflict.is_(True)),
        "bills_with_payments": matches(ReconciliationMatch.status == "confirmed", ReconciliationMatch.kind == "bill_payment"),
        "payments_without_receipts": sources(SourceRecord.role == "payment", SourceRecord.direction == "out", CanonicalTransaction.type == "expense", SourceRecord.reconciliation_status == "unmatched"),
        "receipts_without_payments": sources(SourceRecord.role == "bill", SourceRecord.reconciliation_status.in_(("unmatched", "suggested_match"))),
        "partially_paid_bills": sources(SourceRecord.role == "bill", SourceRecord.reconciliation_status == "partially_paid"),
        "unallocated_payments": sources(SourceRecord.role == "payment", SourceRecord.reconciliation_status == "partially_reconciled"),
        "over_or_underpaid": [serialize_match(db, m) for m in overpaid],
        "unmatched_statement_entries": sources(SourceRecord.source_type == "statement_row", SourceRecord.reconciliation_status == "unmatched"),
        "duplicate_uploads": [
            {
                "id": str(d.id),
                "kind": d.kind,
                "attempted_filename": d.attempted_filename,
                "existing_document_id": str(d.existing_document_id) if d.existing_document_id else None,
                "existing_statement_row_id": str(d.existing_statement_row_id) if d.existing_statement_row_id else None,
                "details": d.details,
                "created_at": d.created_at.isoformat(),
            }
            for d in dup_uploads
        ],
    }


@router.post("/duplicate-uploads/{candidate_id}/dismiss")
def dismiss_duplicate_upload(candidate_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    d = ctx.db.get(DuplicateCandidate, candidate_id)
    if d is None or d.household_id != ctx.household_id:
        raise NotFound("Not found")
    d.status = "dismissed"
    ctx.db.commit()
    return {"ok": True}


@router.post("/manual-match")
def manual_match(body: ManualMatchIn, ctx: Ctx = Depends(writer_ctx), idempotency_key: str | None = Header(default=None)):
    def run():
        x = service.resolve_source(ctx, body.a_source_id, body.a_transaction_id)
        y = service.resolve_source(ctx, body.b_source_id, body.b_transaction_id)
        m = service.manual_match(ctx, x, y, body.amount, body.note, body.kind, body.as_reversal)
        return serialize_match(ctx.db, m, detail=True)

    return run_idempotent(ctx, idempotency_key, "POST", "/reconciliation/manual-match", body.model_dump(mode="json"), run)


@router.post("/allocate-payment")
def allocate_payment(body: AllocateIn, ctx: Ctx = Depends(writer_ctx), idempotency_key: str | None = Header(default=None)):
    def run():
        payment = service.resolve_source(ctx, body.payment_source_id, body.payment_transaction_id, role="payment")
        items = []
        for it in body.allocations:
            bill = service.resolve_source(ctx, it.bill_source_id, it.bill_transaction_id, role="bill")
            items.append((bill, it.amount))
        allocs = service.allocate_payment(ctx, payment, items, body.note)
        p = ctx.db.get(SourceRecord, payment.id)
        return {"allocations": [serialize_allocation(ctx.db, a) for a in allocs], "payment": serialize_source(p)}

    return run_idempotent(ctx, idempotency_key, "POST", "/reconciliation/allocate-payment", body.model_dump(mode="json"), run)


@router.post("/unlink")
def unlink(body: UnlinkIn, ctx: Ctx = Depends(writer_ctx)):
    if not body.match_id and not body.allocation_id:
        raise ValidationFailed("Provide match_id or allocation_id")
    return service.unlink(ctx, body.match_id, body.allocation_id, body.note)


@router.post("/recalculate")
def recalculate(ctx: Ctx = Depends(writer_ctx), regenerate: bool = True):
    return service.recalculate(ctx, regenerate)


@router.post("/bulk-confirm")
def bulk_confirm(body: BulkConfirmIn, ctx: Ctx = Depends(writer_ctx)):
    if not body.confirm:
        raise ValidationFailed("Set confirm=true to acknowledge linking these records", code="confirmation_required")
    results = []
    for mid in body.match_ids:
        try:
            m = service.confirm_match(ctx, mid, note="Bulk confirmed")
            results.append({"id": str(mid), "ok": True, "status": m.status})
        except Exception as exc:  # report per item; one failure must not hide others
            ctx.db.rollback()
            results.append({"id": str(mid), "ok": False, "error": getattr(exc, "message", str(exc)), "code": getattr(exc, "code", "error")})
    return {"results": results, "confirmed": sum(1 for r in results if r["ok"])}


@router.get("/{match_id}")
def get_match(match_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    m = ctx.db.get(ReconciliationMatch, match_id)
    if m is None or m.household_id != ctx.household_id:
        raise NotFound("Reconciliation match not found")
    return serialize_match(ctx.db, m, detail=True)


@router.post("/{match_id}/confirm")
def confirm(match_id: uuid.UUID, body: ConfirmIn, ctx: Ctx = Depends(writer_ctx), idempotency_key: str | None = Header(default=None)):
    def run():
        m = service.confirm_match(ctx, match_id, body.amount, body.note, body.as_reversal)
        return serialize_match(ctx.db, m, detail=True)

    return run_idempotent(ctx, idempotency_key, "POST", f"/reconciliation/{match_id}/confirm", body.model_dump(mode="json"), run)


@router.post("/{match_id}/reject")
def reject(match_id: uuid.UUID, body: RejectIn, ctx: Ctx = Depends(writer_ctx)):
    m = service.reject_match(ctx, match_id, body.note, body.separate_purchases)
    return serialize_match(ctx.db, m, detail=True)


@router.post("/{match_id}/reopen")
def reopen(match_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    m = service.reopen(ctx, match_id)
    return serialize_match(ctx.db, m, detail=True)

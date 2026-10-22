import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import Field
from sqlalchemy import or_, select

from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.idempotency import run_idempotent
from app.models import AuditLog, CanonicalTransaction, ReconciliationAuditLog, SourceRecord
from app.modules.categories.service import CategoryIndex
from app.modules.common import Schema, audit, paginate
from app.modules.ledger.service import (
    TransactionIn,
    TransactionPatch,
    create_transaction,
    get_transaction,
    name_lookup,
    serialize_transaction,
    update_transaction,
    void_transaction,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


class VoidIn(Schema):
    reason: str = Field(default="", max_length=500)


def filtered_query(
    ctx: Ctx,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    month: str | None = None,
    category_id: uuid.UUID | None = None,
    merchant_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    type: list[str] | None = None,
    payment_method: str | None = None,
    account_id: uuid.UUID | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    tag: str | None = None,
    q: str | None = None,
    document_id: uuid.UUID | None = None,
    reconciliation_status: str | None = None,
    status: str = "active",
    source_type: str | None = None,
):
    ct = CanonicalTransaction
    stmt = select(ct).where(ct.household_id == ctx.household_id)
    if status != "all":
        stmt = stmt.where(ct.status.in_(status.split(",")))
    if month:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
        end = date(y + (m == 12), (m % 12) + 1, 1)
        stmt = stmt.where(ct.occurred_on >= start, ct.occurred_on < end)
    if date_from:
        stmt = stmt.where(ct.occurred_on >= date_from)
    if date_to:
        stmt = stmt.where(ct.occurred_on <= date_to)
    if category_id:
        stmt = stmt.where(ct.category_id.in_(CategoryIndex(ctx.db, ctx.household_id).subtree(category_id)))
    if merchant_id:
        stmt = stmt.where(ct.merchant_id == merchant_id)
    if counterparty_id:
        stmt = stmt.where(ct.counterparty_id == counterparty_id)
    if type:
        stmt = stmt.where(ct.type.in_(type))
    if payment_method:
        stmt = stmt.where(ct.payment_method == payment_method)
    if account_id:
        stmt = stmt.where(or_(ct.account_id == account_id, ct.to_account_id == account_id))
    if min_amount is not None:
        stmt = stmt.where(ct.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(ct.amount <= max_amount)
    if tag:
        stmt = stmt.where(ct.tags.contains([tag]))
    if q:
        stmt = stmt.where(or_(ct.description.ilike(f"%{q}%"), ct.notes.ilike(f"%{q}%")))
    if reconciliation_status:
        stmt = stmt.where(ct.reconciliation_status.in_(reconciliation_status.split(",")))
    if document_id or source_type:
        sub = select(SourceRecord.canonical_transaction_id).where(SourceRecord.household_id == ctx.household_id)
        if document_id:
            sub = sub.where(SourceRecord.document_id == document_id)
        if source_type:
            sub = sub.where(SourceRecord.source_type.in_(source_type.split(",")))
        stmt = stmt.where(ct.id.in_(sub))
    return stmt


@router.get("")
def list_transactions(
    ctx: Ctx = Depends(get_ctx),
    page: int = 1,
    page_size: int = Query(50, le=200),
    date_from: date | None = None,
    date_to: date | None = None,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    category_id: uuid.UUID | None = None,
    merchant_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    type: list[str] | None = Query(None),
    payment_method: str | None = None,
    account_id: uuid.UUID | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    tag: str | None = None,
    q: str | None = Query(None, max_length=200),
    document_id: uuid.UUID | None = None,
    reconciliation_status: str | None = None,
    status: str = "active",
    source_type: str | None = None,
    sort: str = Query("-occurred_on", pattern=r"^-?(occurred_on|amount|created_at)$"),
):
    stmt = filtered_query(
        ctx, date_from=date_from, date_to=date_to, month=month, category_id=category_id, merchant_id=merchant_id,
        counterparty_id=counterparty_id, type=type, payment_method=payment_method, account_id=account_id,
        min_amount=min_amount, max_amount=max_amount, tag=tag, q=q, document_id=document_id,
        reconciliation_status=reconciliation_status, status=status, source_type=source_type,
    )
    col = getattr(CanonicalTransaction, sort.lstrip("-"))
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col.asc(), CanonicalTransaction.created_at.desc())
    items, total, page, page_size = paginate(ctx.db, stmt, page, page_size)
    names = name_lookup(ctx.db, ctx.household_id, items)
    return {"items": [serialize_transaction(ctx.db, t, names=names) for t in items], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create(body: TransactionIn, ctx: Ctx = Depends(writer_ctx), idempotency_key: str | None = Header(default=None)):
    def run():
        ct = create_transaction(ctx, body)
        return serialize_transaction(ctx.db, ct, detail=True, names=name_lookup(ctx.db, ctx.household_id, [ct]))

    return run_idempotent(ctx, idempotency_key, "POST", "/transactions", body.model_dump(mode="json"), run)


class RecategorizeIn(Schema):
    only_uncategorized: bool = False


@router.post("/recategorize")
def recategorize(body: RecategorizeIn, ctx: Ctx = Depends(writer_ctx)):
    """Re-applies automatic categorisation (with the bill text where a document exists) to transactions whose
    category was chosen automatically. Categories a person chose or confirmed are never changed."""
    from app.models import Category, ExtractedDocument, Merchant
    from app.modules.categories.service import categorize

    db = ctx.db
    q = select(CanonicalTransaction).where(
        CanonicalTransaction.household_id == ctx.household_id,
        CanonicalTransaction.status == "active",
        CanonicalTransaction.type.in_(("expense", "income", "refund")),
        CanonicalTransaction.category_source.not_in(("manual", "confirmed")),
    )
    if body.only_uncategorized:
        q = q.where(CanonicalTransaction.category_source == "uncategorized")
    names = {c.id: c.name for c in db.scalars(select(Category).where(Category.household_id == ctx.household_id)).all()}
    changed, checked = [], 0
    for ct in db.scalars(q).all():
        checked += 1
        merchant = db.get(Merchant, ct.merchant_id) if ct.merchant_id else None
        doc_text = ""
        doc_ids = [s.document_id for s in db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id == ct.id)).all() if s.document_id]
        if doc_ids:
            ext = db.scalars(select(ExtractedDocument).where(ExtractedDocument.document_id == doc_ids[0])).first()
            doc_text = ext.raw_text if ext else ""
        res = categorize(
            db,
            ctx.household_id,
            description=ct.description,
            merchant_name=merchant.name if merchant else "",
            merchant_id=ct.merchant_id,
            item_names=[li.name for li in ct.line_items],
            tx_type="income" if ct.type == "income" else "expense",
            document_text=doc_text,
        )
        if res["category_id"] and res["category_id"] != ct.category_id:
            changed.append({"id": str(ct.id), "description": ct.description, "from": names.get(ct.category_id), "to": names.get(res["category_id"]), "reasons": res.get("reasons") or []})
            ct.category_id = res["category_id"]
            ct.category_source = res["source"]
            ct.category_reasons = res.get("reasons") or []
            ct.version += 1
    audit(ctx, "recategorize", "transaction", None, None, {"checked": checked, "changed": len(changed)})
    db.commit()
    return {"checked": checked, "changed": changed}


@router.get("/{tx_id}")
def get_one(tx_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    ct = get_transaction(ctx, tx_id)
    return serialize_transaction(ctx.db, ct, detail=True, names=name_lookup(ctx.db, ctx.household_id, [ct]))


@router.patch("/{tx_id}")
def patch(tx_id: uuid.UUID, body: TransactionPatch, ctx: Ctx = Depends(writer_ctx)):
    ct = update_transaction(ctx, tx_id, body)
    return serialize_transaction(ctx.db, ct, detail=True, names=name_lookup(ctx.db, ctx.household_id, [ct]))


@router.post("/{tx_id}/void")
def void(tx_id: uuid.UUID, body: VoidIn, ctx: Ctx = Depends(writer_ctx)):
    ct = void_transaction(ctx, tx_id, body.reason)
    return serialize_transaction(ctx.db, ct, detail=True, names=name_lookup(ctx.db, ctx.household_id, [ct]))


@router.get("/{tx_id}/audit")
def audit_history(tx_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    get_transaction(ctx, tx_id)
    rows = ctx.db.scalars(
        select(AuditLog).where(AuditLog.household_id == ctx.household_id, AuditLog.entity_type == "transaction", AuditLog.entity_id == str(tx_id)).order_by(AuditLog.created_at)
    ).all()
    src_ids = ctx.db.scalars(select(SourceRecord.id).where(or_(SourceRecord.canonical_transaction_id == tx_id, SourceRecord.original_transaction_id == tx_id))).all()
    recon = []
    if src_ids:
        from app.models import ReconciliationMatch

        match_ids = ctx.db.scalars(select(ReconciliationMatch.id).where(or_(ReconciliationMatch.a_source_id.in_(src_ids), ReconciliationMatch.b_source_id.in_(src_ids)))).all()
        if match_ids:
            recon = ctx.db.scalars(select(ReconciliationAuditLog).where(ReconciliationAuditLog.match_id.in_(match_ids)).order_by(ReconciliationAuditLog.created_at)).all()
    events = [
        {"at": r.created_at.isoformat(), "action": r.action, "actor_id": str(r.actor_id) if r.actor_id else None, "before": r.before, "after": r.after, "kind": "ledger"}
        for r in rows
    ] + [
        {"at": r.created_at.isoformat(), "action": r.action, "actor_id": str(r.actor_id) if r.actor_id else None, "before": r.before, "after": r.after, "note": r.note, "kind": "reconciliation"}
        for r in recon
    ]
    return sorted(events, key=lambda e: e["at"])

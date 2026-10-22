import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import Ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import quantize
from app.models import (
    Account,
    CanonicalTransaction,
    Category,
    Counterparty,
    Merchant,
    ReconciliationAllocation,
    ReconciliationAuditLog,
    ReconciliationMatch,
    SourceRecord,
    TransactionLineItem,
)
from app.models.finance import PAYMENT_METHODS, TRANSACTION_TYPES
from app.modules.categories.service import CategoryIndex, categorize, categorize_item
from app.modules.common import Money, OptMoney, Schema, audit, snapshot
from app.modules.merchants.normalize import normalize_merchant
from app.modules.merchants.service import resolve_merchant
from app.modules.prices.units import normalize_quantity
from app.modules.reconciliation import engine
from app.modules.reconciliation.state import bill_settlement, recompute_for_sources, recompute_transaction


class LineItemIn(Schema):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = None
    quantity: OptMoney = None
    unit: str | None = Field(default=None, max_length=20)
    unit_price: OptMoney = None
    discount: OptMoney = None
    tax: OptMoney = None
    line_total: OptMoney = None
    category_id: uuid.UUID | None = None


class TransactionIn(Schema):
    type: str = "expense"
    occurred_on: date
    occurred_at: datetime | None = None
    description: str = Field(default="", max_length=500)
    amount: Money
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    category_id: uuid.UUID | None = None
    merchant_name: str | None = Field(default=None, max_length=200)
    merchant_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    payment_method: str | None = None
    notes: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    line_items: list[LineItemIn] = Field(default_factory=list, max_length=500)
    record_as: str = Field(default="payment", pattern="^(payment|bill)$")
    upi_txn_id: str | None = Field(default=None, max_length=64)
    utr: str | None = Field(default=None, max_length=64)
    bank_ref: str | None = Field(default=None, max_length=64)
    invoice_number: str | None = Field(default=None, max_length=64)
    order_id: str | None = Field(default=None, max_length=64)
    related_transaction_id: uuid.UUID | None = None
    is_recurring: bool = False

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v not in TRANSACTION_TYPES:
            raise ValueError(f"type must be one of {', '.join(TRANSACTION_TYPES)}")
        return v

    @field_validator("payment_method")
    @classmethod
    def _pm(cls, v):
        if v is not None and v not in PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {', '.join(PAYMENT_METHODS)}")
        return v

    @field_validator("amount")
    @classmethod
    def _amount(cls, v):
        if v <= 0:
            raise ValueError("amount must be greater than zero")
        if v > Decimal("1000000000000"):
            raise ValueError("amount is unrealistically large")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        return sorted({t.strip()[:40] for t in v if t and t.strip()})

    @model_validator(mode="after")
    def _transfer(self):
        if self.type in ("transfer", "credit_card_payment"):
            # Imports see only one side of a transfer, so one account is enough; the UI asks for both.
            if not self.account_id and not self.to_account_id:
                raise ValueError("Transfers need a source or destination account")
            if self.account_id and self.account_id == self.to_account_id:
                raise ValueError("Source and destination accounts must differ")
        if self.record_as == "bill" and self.type != "expense":
            raise ValueError("Only expenses can be recorded as a bill")
        return self


class TransactionPatch(Schema):
    version: int | None = None
    type: str | None = None
    occurred_on: date | None = None
    occurred_at: datetime | None = None
    description: str | None = Field(default=None, max_length=500)
    amount: OptMoney = None
    category_id: uuid.UUID | None = None
    merchant_name: str | None = None
    counterparty_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    payment_method: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None
    is_recurring: bool | None = None
    review_status: str | None = Field(default=None, pattern="^(confirmed|needs_review|disputed)$")
    remember_category_for_merchant: bool = False


def _own(ctx: Ctx, model, obj_id, label: str):
    if obj_id is None:
        return None
    obj = ctx.db.get(model, obj_id)
    if obj is None or obj.household_id != ctx.household_id:
        raise NotFound(f"{label} not found")
    return obj


def validate_refs(ctx: Ctx, *, category_id=None, counterparty_id=None, account_id=None, to_account_id=None, merchant_id=None, currency=None):
    _own(ctx, Category, category_id, "Category")
    _own(ctx, Counterparty, counterparty_id, "Counterparty")
    _own(ctx, Merchant, merchant_id, "Merchant")
    for acc_id in (account_id, to_account_id):
        acc = _own(ctx, Account, acc_id, "Account")
        if acc and currency and acc.currency != currency:
            raise ValidationFailed(f"Account '{acc.name}' is in {acc.currency}; the transaction is in {currency}", code="currency_mismatch")


def build_line_items(db: Session, household_id, ct: CanonicalTransaction, items: list[LineItemIn]) -> None:
    idx = CategoryIndex(db, household_id)
    for pos, it in enumerate(items):
        dim, base_qty = normalize_quantity(it.quantity, it.unit)
        ct.line_items.append(
            TransactionLineItem(
                household_id=household_id,
                position=pos,
                name=it.name.strip(),
                normalized_name=" ".join(normalize_merchant_like(it.name)),
                brand=it.brand,
                quantity=it.quantity,
                unit=it.unit,
                unit_price=quantize(it.unit_price, ct.currency) if it.unit_price is not None else None,
                discount=quantize(it.discount, ct.currency) if it.discount is not None else None,
                tax=quantize(it.tax, ct.currency) if it.tax is not None else None,
                line_total=quantize(it.line_total, ct.currency) if it.line_total is not None else None,
                category_id=it.category_id or categorize_item(idx, it.name),
                unit_dimension=dim,
                base_quantity=base_qty,
            )
        )


def normalize_merchant_like(name: str) -> list[str]:
    import re

    return [t for t in re.sub(r"[^a-z0-9\s]", " ", name.lower()).split() if t]


def create_transaction(
    ctx: Ctx,
    data: TransactionIn,
    *,
    source_type: str = "manual",
    document_id=None,
    statement_row_id=None,
    category_source: str | None = None,
    run_matching: bool = True,
    commit: bool = True,
    context_text: str = "",
) -> CanonicalTransaction:
    """Creates a canonical transaction plus the source record that evidences it, then generates match suggestions.

    context_text is the full text of the originating bill, if any; categorisation weighs it as evidence."""
    db = ctx.db
    validate_refs(
        ctx,
        category_id=data.category_id,
        counterparty_id=data.counterparty_id,
        account_id=data.account_id,
        to_account_id=data.to_account_id,
        merchant_id=data.merchant_id,
        currency=data.currency,
    )
    if data.related_transaction_id:
        _own(ctx, CanonicalTransaction, data.related_transaction_id, "Related transaction")
    amount = quantize(data.amount, data.currency)
    merchant = db.get(Merchant, data.merchant_id) if data.merchant_id else resolve_merchant(db, ctx.household_id, data.merchant_name)
    counterparty = db.get(Counterparty, data.counterparty_id) if data.counterparty_id else None

    tx_type = data.type
    category_id = data.category_id
    cat_source = category_source or ("manual" if category_id else "auto")
    cat_reasons: list = []
    if category_id is None:
        res = categorize(
            db,
            ctx.household_id,
            description=data.description,
            merchant_name=(merchant.name if merchant else data.merchant_name) or "",
            merchant_id=merchant.id if merchant else None,
            counterparty_name=counterparty.name if counterparty else "",
            item_names=[i.name for i in data.line_items],
            tx_type=tx_type,
            document_text=context_text,
        )
        category_id = res["category_id"]
        cat_source = res["source"]
        cat_reasons = res.get("reasons") or []
        if cat_source == "uncategorized" and tx_type == "expense":
            category_id, cat_source = _ai_category(ctx, data, merchant, category_id, cat_source)
            if cat_source == "ai":
                cat_reasons = ["AI suggestion (no rule or keyword matched)"]
        if res.get("set_type") and source_type == "statement_row":
            tx_type = res["set_type"]

    ct = CanonicalTransaction(
        id=uuid.uuid4(),
        household_id=ctx.household_id,
        created_by=ctx.user.id,
        type=tx_type,
        occurred_on=data.occurred_on,
        occurred_at=data.occurred_at,
        description=(data.description or (merchant.name if merchant else "") or (counterparty.name if counterparty else "")).strip()[:500],
        amount=amount,
        effective_amount=amount,
        cash_amount=amount,
        currency=data.currency,
        category_id=category_id,
        category_source=cat_source,
        category_reasons=cat_reasons,
        merchant_id=merchant.id if merchant else None,
        counterparty_id=data.counterparty_id,
        account_id=data.account_id,
        to_account_id=data.to_account_id,
        payment_method=data.payment_method,
        notes=data.notes,
        tags=data.tags,
        related_transaction_id=data.related_transaction_id,
        is_recurring=data.is_recurring,
    )
    db.add(ct)
    build_line_items(db, ctx.household_id, ct, data.line_items)
    db.flush()
    direction = TRANSACTION_TYPES[tx_type]
    src = SourceRecord(
        household_id=ctx.household_id,
        canonical_transaction_id=ct.id,
        original_transaction_id=ct.id,
        source_type=source_type,
        role=data.record_as,
        direction=direction,
        amount=amount,
        currency=data.currency,
        occurred_on=data.occurred_on,
        occurred_at=data.occurred_at,
        merchant_raw=(data.merchant_name or (merchant.name if merchant else "") or (counterparty.name if counterparty else ""))[:300],
        merchant_normalized=normalize_merchant(data.merchant_name or (merchant.name if merchant else "")),
        merchant_id=merchant.id if merchant else None,
        description=ct.description,
        payment_method=data.payment_method,
        account_id=data.account_id,
        upi_txn_id=data.upi_txn_id,
        utr=data.utr,
        bank_ref=data.bank_ref,
        invoice_number=data.invoice_number,
        order_id=data.order_id,
        item_names=sorted({" ".join(normalize_merchant_like(i.name)) for i in data.line_items}),
        document_id=document_id,
        statement_row_id=statement_row_id,
    )
    db.add(src)
    db.flush()
    if run_matching:
        engine.generate_candidates(db, ctx.household, src)
    recompute_for_sources(db, [src.id] + _matched_counterparts(db, src.id))
    audit(ctx, "create", "transaction", ct.id, None, snapshot(ct))
    if commit:
        db.commit()
    return ct


def _ai_category(ctx: Ctx, data: "TransactionIn", merchant, category_id, cat_source):
    """Step 5 of categorisation: optional AI suggestion, used only when every deterministic step failed."""
    from app.modules.ai.provider import ai_enabled, suggest_category

    if not ai_enabled(ctx.household):
        return category_id, cat_source
    idx = CategoryIndex(ctx.db, ctx.household_id)
    names = {c.name: c.id for c in idx.by_id.values() if c.kind == "expense"}
    name = suggest_category(ctx.household, data.description, merchant.name if merchant else (data.merchant_name or ""), sorted(names))
    return (names[name], "ai") if name else (category_id, cat_source)


def _matched_counterparts(db: Session, source_id) -> list:
    rows = db.execute(
        select(ReconciliationMatch.a_source_id, ReconciliationMatch.b_source_id).where(
            or_(ReconciliationMatch.a_source_id == source_id, ReconciliationMatch.b_source_id == source_id)
        )
    ).all()
    return [x for r in rows for x in r if x != source_id]


def get_transaction(ctx: Ctx, tx_id: uuid.UUID) -> CanonicalTransaction:
    return _own(ctx, CanonicalTransaction, tx_id, "Transaction")


def update_transaction(ctx: Ctx, tx_id: uuid.UUID, patch: TransactionPatch) -> CanonicalTransaction:
    db = ctx.db
    ct = db.scalars(select(CanonicalTransaction).where(CanonicalTransaction.id == tx_id).with_for_update()).first()
    if ct is None or ct.household_id != ctx.household_id:
        raise NotFound("Transaction not found")
    if patch.version is not None and patch.version != ct.version:
        raise Conflict("This transaction was changed by someone else. Reload and try again.", code="version_conflict")
    if ct.status not in ("active",):
        raise Conflict(f"A {ct.status} transaction cannot be edited", code="not_editable")
    data = patch.model_dump(exclude_unset=True)
    data.pop("version", None)
    remember = data.pop("remember_category_for_merchant", False)
    if "type" in data and data["type"] not in TRANSACTION_TYPES:
        raise ValidationFailed("Unknown transaction type")
    if "payment_method" in data and data["payment_method"] is not None and data["payment_method"] not in PAYMENT_METHODS:
        raise ValidationFailed("Unknown payment method")
    validate_refs(
        ctx,
        category_id=data.get("category_id"),
        counterparty_id=data.get("counterparty_id"),
        account_id=data.get("account_id"),
        to_account_id=data.get("to_account_id"),
        currency=ct.currency,
    )
    before = snapshot(ct)
    sources = db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id == ct.id).with_for_update()).all()
    evidence_fields = {"amount", "occurred_on", "occurred_at", "type"}
    touches_evidence = bool(evidence_fields & set(data))
    if touches_evidence:
        if any(s.source_type != "manual" for s in sources):
            raise Conflict(
                "Amount, date and type come from an uploaded document or imported statement. Correct the source document, or unlink it first.",
                code="evidence_locked",
            )
        if "amount" in data:
            if data["amount"] is None or data["amount"] <= 0:
                raise ValidationFailed("amount must be greater than zero")
            new_amount = quantize(data["amount"], ct.currency)
            for s in sources:
                if Decimal(s.allocated_amount) > new_amount:
                    raise Conflict(
                        f"{s.allocated_amount} is already allocated; the amount cannot go below that. Unlink allocations first.",
                        code="amount_below_allocated",
                    )
            data["amount"] = new_amount
        if "type" in data and any(Decimal(s.allocated_amount) > 0 for s in sources):
            raise Conflict("Unlink allocations before changing the transaction type", code="has_allocations")
    merchant_changed = "merchant_name" in data
    if merchant_changed:
        m = resolve_merchant(db, ctx.household_id, data.pop("merchant_name"))
        ct.merchant_id = m.id if m else None
    if "tags" in data and data["tags"] is not None:
        data["tags"] = sorted({t.strip()[:40] for t in data["tags"] if t and t.strip()})
    for k, v in data.items():
        setattr(ct, k, v)
    if "category_id" in data:
        # A user's choice; it also teaches future bills from this merchant (see categorize step 2).
        ct.category_source = "manual"
        ct.category_reasons = []
        if remember and ct.merchant_id and ct.category_id:
            db.get(Merchant, ct.merchant_id).default_category_id = ct.category_id
    if touches_evidence:
        for s in sources:
            if "amount" in data:
                s.amount = ct.amount
            if "occurred_on" in data:
                s.occurred_on = ct.occurred_on
            if "occurred_at" in data:
                s.occurred_at = ct.occurred_at
            if "type" in data:
                s.direction = TRANSACTION_TYPES[ct.type]
    if merchant_changed:
        for s in sources:
            if s.source_type == "manual" and ct.merchant_id:
                s.merchant_id = ct.merchant_id
                m = db.get(Merchant, ct.merchant_id)
                s.merchant_raw = m.name
                s.merchant_normalized = m.normalized_name
    ct.version += 1
    db.flush()
    recompute_transaction(db, ct)
    if touches_evidence or merchant_changed:
        for s in sources:
            engine.generate_candidates(db, ctx.household, s)
        recompute_for_sources(db, [s.id for s in sources] + [x for s in sources for x in _matched_counterparts(db, s.id)])
    audit(ctx, "update", "transaction", ct.id, before, snapshot(ct))
    db.commit()
    return ct


def void_transaction(ctx: Ctx, tx_id: uuid.UUID, reason: str = "") -> CanonicalTransaction:
    """Voids a transaction (never hard-deletes): its sources stop counting and every link is undone and audited."""
    db = ctx.db
    ct = db.scalars(select(CanonicalTransaction).where(CanonicalTransaction.id == tx_id).with_for_update()).first()
    if ct is None or ct.household_id != ctx.household_id:
        raise NotFound("Transaction not found")
    if ct.status == "voided":
        return ct
    if ct.status == "merged":
        raise Conflict("This record is merged into another transaction. Unlink the duplicate match instead.", code="merged")
    before = snapshot(ct)
    sources = db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id == ct.id).with_for_update()).all()
    touched = []
    for s in sources:
        s.status = "voided"
        allocs = db.scalars(
            select(ReconciliationAllocation).where(
                or_(ReconciliationAllocation.payment_source_id == s.id, ReconciliationAllocation.bill_source_id == s.id),
                ReconciliationAllocation.status == "active",
            )
        ).all()
        for a in allocs:
            a.status = "removed"
            a.removed_by = ctx.user.id
            a.removed_at = utcnow()
            touched += [a.payment_source_id, a.bill_source_id]
            db.add(ReconciliationAuditLog(household_id=ctx.household_id, match_id=a.match_id, allocation_id=a.id, action="allocation_removed_by_void", actor_id=ctx.user.id, note=reason))
        for m in db.scalars(select(ReconciliationMatch).where(or_(ReconciliationMatch.a_source_id == s.id, ReconciliationMatch.b_source_id == s.id), ReconciliationMatch.status == "suggested")).all():
            m.status = "rejected"
            m.note = "Record voided"
            touched += [m.a_source_id, m.b_source_id]
    # Duplicates merged into this transaction describe the same voided event.
    for merged in db.scalars(select(CanonicalTransaction).where(CanonicalTransaction.merged_into_id == ct.id)).all():
        merged.status = "voided"
    ct.status = "voided"
    ct.version += 1
    db.flush()
    recompute_for_sources(db, [s.id for s in sources] + touched)
    audit(ctx, "void", "transaction", ct.id, before, {**snapshot(ct), "reason": reason})
    db.commit()
    return ct


def serialize_transaction(db: Session, ct: CanonicalTransaction, detail: bool = False, names: dict | None = None) -> dict:
    names = names or {}
    out = {
        "id": str(ct.id),
        "type": ct.type,
        "occurred_on": ct.occurred_on.isoformat(),
        "occurred_at": ct.occurred_at.isoformat() if ct.occurred_at else None,
        "description": ct.description,
        "amount": format(quantize(ct.amount, ct.currency), "f"),
        "effective_amount": format(quantize(ct.effective_amount, ct.currency), "f"),
        "cash_amount": format(quantize(ct.cash_amount, ct.currency), "f"),
        "currency": ct.currency,
        "category_id": str(ct.category_id) if ct.category_id else None,
        "category_name": names.get(ct.category_id),
        "category_source": ct.category_source,
        "category_reasons": ct.category_reasons or [],
        "merchant_id": str(ct.merchant_id) if ct.merchant_id else None,
        "merchant_name": names.get(ct.merchant_id),
        "counterparty_id": str(ct.counterparty_id) if ct.counterparty_id else None,
        "counterparty_name": names.get(ct.counterparty_id),
        "account_id": str(ct.account_id) if ct.account_id else None,
        "account_name": names.get(ct.account_id),
        "to_account_id": str(ct.to_account_id) if ct.to_account_id else None,
        "payment_method": ct.payment_method,
        "notes": ct.notes,
        "tags": ct.tags or [],
        "status": ct.status,
        "merged_into_id": str(ct.merged_into_id) if ct.merged_into_id else None,
        "related_transaction_id": str(ct.related_transaction_id) if ct.related_transaction_id else None,
        "reconciliation_status": ct.reconciliation_status,
        "review_status": ct.review_status,
        "is_recurring": ct.is_recurring,
        "version": ct.version,
        "created_at": ct.created_at.isoformat(),
        "updated_at": ct.updated_at.isoformat(),
    }
    if detail:
        sources = db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id == ct.id).order_by(SourceRecord.created_at)).all()
        out["sources"] = [serialize_source(s) for s in sources]
        out["line_items"] = [
            {
                "id": str(li.id),
                "name": li.name,
                "brand": li.brand,
                "quantity": _s(li.quantity),
                "unit": li.unit,
                "unit_price": _s(li.unit_price),
                "discount": _s(li.discount),
                "tax": _s(li.tax),
                "line_total": _s(li.line_total),
                "category_id": str(li.category_id) if li.category_id else None,
            }
            for li in ct.line_items
        ]
        settle = bill_settlement(db, ct)
        out["settlement"] = {k: (format(quantize(v, ct.currency), "f") if isinstance(v, Decimal) else v) for k, v in settle.items()} if settle else None
        src_ids = [s.id for s in sources]
        allocs = db.scalars(
            select(ReconciliationAllocation).where(
                or_(ReconciliationAllocation.payment_source_id.in_(src_ids), ReconciliationAllocation.bill_source_id.in_(src_ids)),
                ReconciliationAllocation.status == "active",
            )
        ).all() if src_ids else []
        out["allocations"] = [serialize_allocation(db, a) for a in allocs]
        out["merged_duplicates"] = [str(x) for x in db.scalars(select(CanonicalTransaction.id).where(CanonicalTransaction.merged_into_id == ct.id)).all()]
    return out


def _s(v):
    return None if v is None else format(Decimal(v), "f")


def serialize_source(s: SourceRecord) -> dict:
    return {
        "id": str(s.id),
        "transaction_id": str(s.canonical_transaction_id),
        "original_transaction_id": str(s.original_transaction_id),
        "source_type": s.source_type,
        "role": s.role,
        "direction": s.direction,
        "amount": format(quantize(s.amount, s.currency), "f"),
        "allocated_amount": format(quantize(s.allocated_amount, s.currency), "f"),
        "available_amount": format(quantize(Decimal(s.amount) - Decimal(s.allocated_amount), s.currency), "f"),
        "currency": s.currency,
        "occurred_on": s.occurred_on.isoformat(),
        "occurred_at": s.occurred_at.isoformat() if s.occurred_at else None,
        "merchant": s.merchant_raw,
        "description": s.description,
        "payment_method": s.payment_method,
        "account_id": str(s.account_id) if s.account_id else None,
        "upi_txn_id": s.upi_txn_id,
        "utr": s.utr,
        "bank_ref": s.bank_ref,
        "invoice_number": s.invoice_number,
        "order_id": s.order_id,
        "document_id": str(s.document_id) if s.document_id else None,
        "statement_row_id": str(s.statement_row_id) if s.statement_row_id else None,
        "status": s.status,
        "reconciliation_status": s.reconciliation_status,
        "item_names": s.item_names,
    }


def serialize_allocation(db: Session, a: ReconciliationAllocation) -> dict:
    p = db.get(SourceRecord, a.payment_source_id)
    b = db.get(SourceRecord, a.bill_source_id)
    return {
        "id": str(a.id),
        "match_id": str(a.match_id) if a.match_id else None,
        "payment_source_id": str(a.payment_source_id),
        "payment_transaction_id": str(p.canonical_transaction_id) if p else None,
        "payment_description": p.description if p else None,
        "bill_source_id": str(a.bill_source_id),
        "bill_transaction_id": str(b.canonical_transaction_id) if b else None,
        "bill_description": b.description if b else None,
        "amount": format(quantize(a.amount, p.currency if p else "INR"), "f"),
        "status": a.status,
        "created_at": a.created_at.isoformat(),
    }


def name_lookup(db: Session, household_id, cts: list[CanonicalTransaction]) -> dict:
    ids_c = {c.category_id for c in cts if c.category_id}
    ids_m = {c.merchant_id for c in cts if c.merchant_id}
    ids_p = {c.counterparty_id for c in cts if c.counterparty_id}
    ids_a = {c.account_id for c in cts if c.account_id}
    out = {}
    if ids_c:
        out.update({i: n for i, n in db.execute(select(Category.id, Category.name).where(Category.id.in_(ids_c))).all()})
    if ids_m:
        out.update({i: n for i, n in db.execute(select(Merchant.id, Merchant.name).where(Merchant.id.in_(ids_m))).all()})
    if ids_p:
        out.update({i: n for i, n in db.execute(select(Counterparty.id, Counterparty.name).where(Counterparty.id.in_(ids_p))).all()})
    if ids_a:
        out.update({i: n for i, n in db.execute(select(Account.id, Account.name).where(Account.id.in_(ids_a))).all()})
    return out

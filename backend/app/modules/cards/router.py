import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.idempotency import run_idempotent
from app.core.money import quantize
from app.models import Account, CanonicalTransaction, CreditCardBillPayment, CreditCardStatement, Document
from app.modules.cards import service as svc
from app.modules.categories.service import CategoryIndex
from app.modules.common import Money, OptMoney, Schema, audit, snapshot
from app.modules.ledger.service import TransactionIn, create_transaction, void_transaction

router = APIRouter(tags=["credit cards"])


@router.get("/credit-cards")
def list_cards(ctx: Ctx = Depends(get_ctx)):
    cards = ctx.db.scalars(
        select(Account).where(Account.household_id == ctx.household_id, Account.type == "credit_card", Account.is_archived.is_(False)).order_by(Account.name)
    ).all()
    return [svc.card_summary(ctx, c) for c in cards]


@router.get("/credit-cards/{account_id}")
def card_detail(account_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    acc = svc.get_card(ctx, account_id)
    statements = ctx.db.scalars(select(CreditCardStatement).where(CreditCardStatement.account_id == acc.id).order_by(CreditCardStatement.statement_date.desc())).all()
    return {**svc.card_summary(ctx, acc), "statements": [svc.serialize_statement(ctx, s) for s in statements]}


@router.get("/credit-cards/{account_id}/statement-preview")
def statement_preview(account_id: uuid.UUID, statement_date: date, period_start: date | None = None, ctx: Ctx = Depends(get_ctx)):
    """Suggests a bill from the card's own transactions. The bank's statement is authoritative; this is a check."""
    acc = svc.get_card(ctx, account_id)
    last = ctx.db.scalars(
        select(CreditCardStatement).where(CreditCardStatement.account_id == acc.id, CreditCardStatement.statement_date < statement_date).order_by(CreditCardStatement.statement_date.desc())
    ).first()
    start = period_start or (last.statement_date + timedelta(days=1) if last else statement_date - timedelta(days=30))
    if start > statement_date:
        raise ValidationFailed("The period must start on or before the statement date")
    due = svc.default_due_date(acc, statement_date)
    return {**svc.cycle_summary(ctx, acc, start, statement_date), "suggested_due_date": due.isoformat() if due else None}


class StatementIn(Schema):
    statement_date: date
    period_start: date | None = None
    due_date: date
    total_due: Money
    minimum_due: Money
    interest_charged: Money = Decimal("0")
    fees_charged: Money = Decimal("0")
    record_charges: bool = Field(default=False, description="Create expense transactions for interest and fees")
    document_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=2000)


class StatementPatch(Schema):
    due_date: date | None = None
    total_due: OptMoney = None
    minimum_due: OptMoney = None
    notes: str | None = Field(default=None, max_length=2000)


def _validate_amounts(total, minimum, interest, fees, statement_date, due_date, period_start):
    if total < 0 or minimum < 0 or interest < 0 or fees < 0:
        raise ValidationFailed("Amounts can't be negative")
    if minimum > total:
        raise ValidationFailed("The minimum due can't be more than the total due", code="minimum_exceeds_total")
    if due_date < statement_date:
        raise ValidationFailed("The due date can't be before the statement date", code="due_before_statement")
    if period_start and period_start > statement_date:
        raise ValidationFailed("The period must start on or before the statement date")


def _get_statement(ctx: Ctx, sid: uuid.UUID, lock: bool = False) -> CreditCardStatement:
    q = select(CreditCardStatement).where(CreditCardStatement.id == sid)
    if lock:
        q = q.with_for_update()
    s = ctx.db.scalars(q).first()
    if s is None or s.household_id != ctx.household_id:
        raise NotFound("Bill not found")
    return s


@router.post("/credit-cards/{account_id}/statements", status_code=201)
def create_statement(account_id: uuid.UUID, body: StatementIn, ctx: Ctx = Depends(writer_ctx)):
    acc = svc.get_card(ctx, account_id)
    cur = acc.currency
    total, minimum = quantize(body.total_due, cur), quantize(body.minimum_due, cur)
    interest, fees = quantize(body.interest_charged, cur), quantize(body.fees_charged, cur)
    last = ctx.db.scalars(
        select(CreditCardStatement).where(CreditCardStatement.account_id == acc.id, CreditCardStatement.statement_date < body.statement_date).order_by(CreditCardStatement.statement_date.desc())
    ).first()
    start = body.period_start or (last.statement_date + timedelta(days=1) if last else body.statement_date - timedelta(days=30))
    _validate_amounts(total, minimum, interest, fees, body.statement_date, body.due_date, start)
    if body.document_id:
        d = ctx.db.get(Document, body.document_id)
        if d is None or d.household_id != ctx.household_id:
            raise NotFound("Document not found")
    s = CreditCardStatement(
        household_id=ctx.household_id,
        account_id=acc.id,
        period_start=start,
        statement_date=body.statement_date,
        due_date=body.due_date,
        total_due=total,
        minimum_due=minimum,
        currency=cur,
        interest_charged=interest,
        fees_charged=fees,
        document_id=body.document_id,
        notes=body.notes,
        created_by=ctx.user.id,
    )
    ctx.db.add(s)
    try:
        ctx.db.flush()
    except IntegrityError:
        ctx.db.rollback()
        raise Conflict("A bill for this card and statement date already exists", code="duplicate_statement")
    if body.record_charges:
        idx = CategoryIndex(ctx.db, ctx.household_id)
        ids = []
        for amount, path, label in (
            (interest, "Loan Interest and Financial Charges/Loan Interest", "Credit card interest"),
            (fees, "Loan Interest and Financial Charges/Bank Charges", "Credit card fees"),
        ):
            if amount > 0:
                ct = create_transaction(
                    ctx,
                    TransactionIn(type="expense", occurred_on=body.statement_date, description=f"{label} - {acc.name}", amount=amount, currency=cur, account_id=acc.id, category_id=idx.resolve(path), payment_method="credit_card"),
                    commit=False,
                )
                ids.append(str(ct.id))
        s.charge_transaction_ids = ids
    audit(ctx, "create", "credit_card_statement", s.id, None, snapshot(s))
    ctx.db.commit()
    return svc.serialize_statement(ctx, s, detail=True)


@router.get("/credit-card-statements/{sid}")
def get_statement(sid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return svc.serialize_statement(ctx, _get_statement(ctx, sid), detail=True)


@router.patch("/credit-card-statements/{sid}")
def update_statement(sid: uuid.UUID, body: StatementPatch, ctx: Ctx = Depends(writer_ctx)):
    s = _get_statement(ctx, sid, lock=True)
    before = snapshot(s)
    data = body.model_dump(exclude_unset=True)
    total = quantize(data.get("total_due", s.total_due), s.currency)
    minimum = quantize(data.get("minimum_due", s.minimum_due), s.currency)
    _validate_amounts(total, minimum, Decimal(s.interest_charged), Decimal(s.fees_charged), s.statement_date, data.get("due_date") or s.due_date, s.period_start)
    s.total_due, s.minimum_due = total, minimum
    if data.get("due_date"):
        s.due_date = data["due_date"]
    if "notes" in data and data["notes"] is not None:
        s.notes = data["notes"]
    audit(ctx, "update", "credit_card_statement", s.id, before, snapshot(s))
    ctx.db.commit()
    return svc.serialize_statement(ctx, s, detail=True)


@router.delete("/credit-card-statements/{sid}")
def delete_statement(sid: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    """Removes the bill and its payment links. Payments themselves stay in the ledger; recorded charges are voided."""
    s = _get_statement(ctx, sid, lock=True)
    before = snapshot(s)
    charge_ids = list(s.charge_transaction_ids or [])
    ctx.db.delete(s)
    ctx.db.flush()
    audit(ctx, "delete", "credit_card_statement", sid, before, None)
    ctx.db.commit()
    for tid in charge_ids:
        t = ctx.db.get(CanonicalTransaction, uuid.UUID(tid))
        if t is not None and t.status == "active":
            void_transaction(ctx, t.id, "Credit card bill deleted")
    return {"ok": True, "voided_charges": charge_ids}


class PayIn(Schema):
    from_account_id: uuid.UUID
    amount: Money
    paid_on: date
    payment_method: str = Field(default="bank_transfer", pattern="^(bank_transfer|net_banking|upi|debit_card|cash|wallet|cheque|other)$")
    reference: str | None = Field(default=None, max_length=64)


@router.post("/credit-card-statements/{sid}/pay", status_code=201)
def pay_bill(sid: uuid.UUID, body: PayIn, ctx: Ctx = Depends(writer_ctx), idempotency_key: str | None = Header(default=None)):
    """Records the payment from a bank/UPI/wallet account to the card and links it to this bill."""

    def run():
        s = _get_statement(ctx, sid, lock=True)
        card = svc.get_card(ctx, s.account_id)
        src = ctx.db.get(Account, body.from_account_id)
        if src is None or src.household_id != ctx.household_id:
            raise NotFound("Account not found")
        if src.id == card.id or src.type == "credit_card":
            raise ValidationFailed("Pay a card bill from a bank, UPI, wallet or cash account", code="invalid_source_account")
        if src.currency != s.currency:
            raise ValidationFailed("The paying account uses a different currency", code="currency_mismatch")
        amount = quantize(body.amount, s.currency)
        if amount <= 0:
            raise ValidationFailed("Amount must be greater than zero")
        ct = create_transaction(
            ctx,
            TransactionIn(
                type="credit_card_payment",
                occurred_on=body.paid_on,
                description=f"Credit card bill payment - {card.name}",
                amount=amount,
                currency=s.currency,
                account_id=src.id,
                to_account_id=card.id,
                payment_method=body.payment_method,
                bank_ref=body.reference,
            ),
            commit=False,
        )
        svc.create_payment_link(ctx, s, card, ct, None)
        audit(ctx, "pay", "credit_card_statement", s.id, None, {"transaction_id": str(ct.id), "amount": format(amount, "f")})
        ctx.db.commit()
        return svc.serialize_statement(ctx, s, detail=True)

    return run_idempotent(ctx, idempotency_key, "POST", f"/credit-card-statements/{sid}/pay", body.model_dump(mode="json"), run)


class LinkIn(Schema):
    transaction_id: uuid.UUID
    amount: OptMoney = None


@router.post("/credit-card-statements/{sid}/link")
def link_payment(sid: uuid.UUID, body: LinkIn, ctx: Ctx = Depends(writer_ctx)):
    """Links an existing payment (for example an imported 'CC PAYMENT' bank row) to this bill."""
    s = _get_statement(ctx, sid, lock=True)
    card = svc.get_card(ctx, s.account_id)
    t = ctx.db.scalars(select(CanonicalTransaction).where(CanonicalTransaction.id == body.transaction_id).with_for_update()).first()
    if t is None:
        raise NotFound("Payment transaction not found")
    link = svc.create_payment_link(ctx, s, card, t, body.amount)
    audit(ctx, "link_payment", "credit_card_statement", s.id, None, {"transaction_id": str(t.id), "amount": format(link.amount, "f")})
    ctx.db.commit()
    return svc.serialize_statement(ctx, s, detail=True)


class UnlinkIn(Schema):
    link_id: uuid.UUID


@router.post("/credit-card-statements/{sid}/unlink")
def unlink_payment(sid: uuid.UUID, body: UnlinkIn, ctx: Ctx = Depends(writer_ctx)):
    s = _get_statement(ctx, sid, lock=True)
    link = ctx.db.get(CreditCardBillPayment, body.link_id)
    if link is None or link.statement_id != s.id:
        raise NotFound("Payment link not found")
    audit(ctx, "unlink_payment", "credit_card_statement", s.id, {"transaction_id": str(link.transaction_id), "amount": format(link.amount, "f")}, None)
    ctx.db.delete(link)
    ctx.db.commit()
    return svc.serialize_statement(ctx, s, detail=True)

"""Counterparties, loans (given/received) with repayments, and shared expenses with settlements.

Rules: loan principal and repayments are cash movements, never spending; only interest is an expense.
A shared bill is one purchase; reimbursements are settlements and never add to the purchase total."""
import uuid
from datetime import date
from decimal import ROUND_DOWN, Decimal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import MINOR_UNITS, quantize
from app.models import CanonicalTransaction, Category, Counterparty, Loan, LoanRepayment, SharedExpense, SharedExpenseParticipant, SharedExpenseSettlement
from app.modules.categories.service import CategoryIndex
from app.modules.common import Money, OptMoney, Schema, audit, snapshot
from app.modules.ledger.service import TransactionIn, create_transaction, void_transaction

router = APIRouter(tags=["people"])
ZERO = Decimal("0")


def _cp(ctx: Ctx, cid) -> Counterparty:
    c = ctx.db.get(Counterparty, cid)
    if c is None or c.household_id != ctx.household_id:
        raise NotFound("Person not found")
    return c


# ------------------------------------------------------------ counterparties
class CounterpartyIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=40)
    upi_id: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)


def _cp_out(c: Counterparty) -> dict:
    return {"id": str(c.id), "name": c.name, "email": c.email, "phone": c.phone, "upi_id": c.upi_id, "notes": c.notes, "is_archived": c.is_archived}


@router.get("/counterparties")
def list_counterparties(ctx: Ctx = Depends(get_ctx), include_archived: bool = False):
    q = select(Counterparty).where(Counterparty.household_id == ctx.household_id).order_by(Counterparty.name)
    if not include_archived:
        q = q.where(Counterparty.is_archived.is_(False))
    return [_cp_out(c) for c in ctx.db.scalars(q).all()]


@router.post("/counterparties", status_code=201)
def create_counterparty(body: CounterpartyIn, ctx: Ctx = Depends(writer_ctx)):
    if ctx.db.scalars(select(Counterparty).where(Counterparty.household_id == ctx.household_id, Counterparty.name == body.name.strip())).first():
        raise Conflict("A person with this name already exists")
    c = Counterparty(household_id=ctx.household_id, **{**body.model_dump(), "name": body.name.strip()})
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "create", "counterparty", c.id, None, snapshot(c))
    ctx.db.commit()
    return _cp_out(c)


@router.patch("/counterparties/{cid}")
def update_counterparty(cid: uuid.UUID, body: CounterpartyIn, ctx: Ctx = Depends(writer_ctx)):
    c = _cp(ctx, cid)
    before = snapshot(c)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit(ctx, "update", "counterparty", c.id, before, snapshot(c))
    ctx.db.commit()
    return _cp_out(c)


@router.delete("/counterparties/{cid}")
def archive_counterparty(cid: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    c = _cp(ctx, cid)
    c.is_archived = True
    audit(ctx, "archive", "counterparty", c.id)
    ctx.db.commit()
    return {"ok": True}


def person_balance(ctx: Ctx, cid) -> dict:
    """Positive receivable = they owe you; positive payable = you owe them."""
    recv = pay = ZERO
    for ln in ctx.db.scalars(select(Loan).options(selectinload(Loan.repayments)).where(Loan.household_id == ctx.household_id, Loan.counterparty_id == cid, Loan.status == "open")).all():
        out = Decimal(ln.principal) - sum((Decimal(r.principal_amount) for r in ln.repayments), ZERO)
        if ln.direction == "given":
            recv += out
        else:
            pay += out
    rows = ctx.db.execute(
        select(SharedExpense.payer_counterparty_id, SharedExpenseParticipant.counterparty_id, SharedExpenseParticipant.share_amount, SharedExpenseParticipant.settled_amount)
        .join(SharedExpense, SharedExpense.id == SharedExpenseParticipant.shared_expense_id)
        .join(CanonicalTransaction, CanonicalTransaction.id == SharedExpense.transaction_id)
        .where(SharedExpense.household_id == ctx.household_id, CanonicalTransaction.status == "active")
    ).all()
    for payer, participant, share, settled in rows:
        open_amt = Decimal(share) - Decimal(settled)
        if payer is None and participant == cid:
            recv += open_amt
        elif payer == cid and participant is None:
            pay += open_amt
    cur = ctx.household.base_currency
    return {"receivable": format(quantize(recv, cur), "f"), "payable": format(quantize(pay, cur), "f"), "net": format(quantize(recv - pay, cur), "f")}


@router.get("/counterparties/balances")
def balances(ctx: Ctx = Depends(get_ctx)):
    people = ctx.db.scalars(select(Counterparty).where(Counterparty.household_id == ctx.household_id, Counterparty.is_archived.is_(False)).order_by(Counterparty.name)).all()
    return [{**_cp_out(c), **person_balance(ctx, c.id)} for c in people]


@router.get("/counterparties/{cid}/ledger")
def person_ledger(cid: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    c = _cp(ctx, cid)
    from app.modules.ledger.service import name_lookup, serialize_transaction

    txs = ctx.db.scalars(
        select(CanonicalTransaction).where(CanonicalTransaction.household_id == ctx.household_id, CanonicalTransaction.counterparty_id == c.id).order_by(CanonicalTransaction.occurred_on.desc())
    ).all()
    names = name_lookup(ctx.db, ctx.household_id, txs)
    return {
        "person": _cp_out(c),
        "balance": person_balance(ctx, c.id),
        "transactions": [serialize_transaction(ctx.db, t, names=names) for t in txs],
        "loans": [_loan_out(ln) for ln in ctx.db.scalars(select(Loan).options(selectinload(Loan.repayments)).where(Loan.counterparty_id == c.id)).all()],
        "shared_expenses": [
            _shared_out(ctx, s)
            for s in ctx.db.scalars(
                select(SharedExpense)
                .options(selectinload(SharedExpense.participants))
                .where(SharedExpense.household_id == ctx.household_id, or_(SharedExpense.payer_counterparty_id == c.id, SharedExpense.participants.any(SharedExpenseParticipant.counterparty_id == c.id)))
            ).all()
        ],
    }


# ------------------------------------------------------------ loans
class LoanIn(Schema):
    counterparty_id: uuid.UUID
    direction: str = Field(pattern="^(given|received)$")
    principal: Money
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    interest_rate_pct: OptMoney = None
    start_date: date
    due_date: date | None = None
    account_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=2000)
    record_disbursement: bool = True


class RepaymentIn(Schema):
    paid_on: date
    principal_amount: Money = Decimal("0")
    interest_amount: Money = Decimal("0")
    account_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=1000)


def _loan_out(ln: Loan) -> dict:
    repaid = sum((Decimal(r.principal_amount) for r in ln.repayments), ZERO)
    interest = sum((Decimal(r.interest_amount) for r in ln.repayments), ZERO)
    return {
        "id": str(ln.id),
        "counterparty_id": str(ln.counterparty_id),
        "direction": ln.direction,
        "principal": format(quantize(ln.principal, ln.currency), "f"),
        "currency": ln.currency,
        "interest_rate_pct": format(Decimal(ln.interest_rate_pct), "f") if ln.interest_rate_pct is not None else None,
        "start_date": ln.start_date.isoformat(),
        "due_date": ln.due_date.isoformat() if ln.due_date else None,
        "status": ln.status,
        "notes": ln.notes,
        "principal_repaid": format(quantize(repaid, ln.currency), "f"),
        "interest_paid": format(quantize(interest, ln.currency), "f"),
        "outstanding": format(quantize(Decimal(ln.principal) - repaid, ln.currency), "f"),
        "transaction_id": str(ln.transaction_id) if ln.transaction_id else None,
        "repayments": [
            {
                "id": str(r.id),
                "paid_on": r.paid_on.isoformat(),
                "principal_amount": format(quantize(r.principal_amount, ln.currency), "f"),
                "interest_amount": format(quantize(r.interest_amount, ln.currency), "f"),
                "transaction_id": str(r.transaction_id) if r.transaction_id else None,
                "interest_transaction_id": str(r.interest_transaction_id) if r.interest_transaction_id else None,
                "notes": r.notes,
            }
            for r in ln.repayments
        ],
    }


@router.get("/loans")
def list_loans(ctx: Ctx = Depends(get_ctx), status: str | None = None):
    q = select(Loan).options(selectinload(Loan.repayments)).where(Loan.household_id == ctx.household_id).order_by(Loan.start_date.desc())
    if status:
        q = q.where(Loan.status == status)
    return [_loan_out(ln) for ln in ctx.db.scalars(q).all()]


@router.post("/loans", status_code=201)
def create_loan(body: LoanIn, ctx: Ctx = Depends(writer_ctx)):
    c = _cp(ctx, body.counterparty_id)
    if body.principal <= 0:
        raise ValidationFailed("Principal must be greater than zero")
    principal = quantize(body.principal, body.currency)
    ln = Loan(
        household_id=ctx.household_id,
        counterparty_id=c.id,
        direction=body.direction,
        principal=principal,
        currency=body.currency,
        interest_rate_pct=body.interest_rate_pct,
        start_date=body.start_date,
        due_date=body.due_date,
        notes=body.notes,
        account_id=body.account_id,
    )
    ctx.db.add(ln)
    ctx.db.flush()
    if body.record_disbursement:
        ct = create_transaction(
            ctx,
            TransactionIn(
                type="loan_given" if body.direction == "given" else "loan_received",
                occurred_on=body.start_date,
                description=f"Loan {'to' if body.direction == 'given' else 'from'} {c.name}",
                amount=principal,
                currency=body.currency,
                counterparty_id=c.id,
                account_id=body.account_id,
            ),
            run_matching=False,
            commit=False,
        )
        ln.transaction_id = ct.id
    audit(ctx, "create", "loan", ln.id, None, snapshot(ln))
    ctx.db.commit()
    ctx.db.refresh(ln)
    return _loan_out(ln)


@router.post("/loans/{loan_id}/repayments", status_code=201)
def add_repayment(loan_id: uuid.UUID, body: RepaymentIn, ctx: Ctx = Depends(writer_ctx)):
    ln = ctx.db.scalars(select(Loan).options(selectinload(Loan.repayments)).where(Loan.id == loan_id).with_for_update()).first()
    if ln is None or ln.household_id != ctx.household_id:
        raise NotFound("Loan not found")
    if ln.status != "open":
        raise Conflict("This loan is already closed", code="loan_closed")
    principal = quantize(body.principal_amount, ln.currency)
    interest = quantize(body.interest_amount, ln.currency)
    if principal < 0 or interest < 0 or principal + interest <= 0:
        raise ValidationFailed("Enter a principal and/or interest amount greater than zero")
    outstanding = Decimal(ln.principal) - sum((Decimal(r.principal_amount) for r in ln.repayments), ZERO)
    if principal > outstanding:
        raise ValidationFailed(f"Principal repayment exceeds the outstanding {outstanding}", code="repayment_exceeds_outstanding")
    person = ctx.db.get(Counterparty, ln.counterparty_id)
    rep = LoanRepayment(loan_id=ln.id, household_id=ctx.household_id, paid_on=body.paid_on, principal_amount=principal, interest_amount=interest, notes=body.notes)
    we_pay = ln.direction == "received"
    if principal > 0:
        ct = create_transaction(
            ctx,
            TransactionIn(
                type="loan_repayment_paid" if we_pay else "loan_repayment_received",
                occurred_on=body.paid_on,
                description=f"Loan repayment {'to' if we_pay else 'from'} {person.name}",
                amount=principal,
                currency=ln.currency,
                counterparty_id=person.id,
                account_id=body.account_id or ln.account_id,
            ),
            run_matching=False,
            commit=False,
        )
        rep.transaction_id = ct.id
    if interest > 0:
        idx = CategoryIndex(ctx.db, ctx.household_id)
        cat = idx.resolve("Loan Interest and Financial Charges/Loan Interest")
        ct_i = create_transaction(
            ctx,
            TransactionIn(
                type="expense" if we_pay else "income",
                occurred_on=body.paid_on,
                description=f"Loan interest {'to' if we_pay else 'from'} {person.name}",
                amount=interest,
                currency=ln.currency,
                counterparty_id=person.id,
                account_id=body.account_id or ln.account_id,
                category_id=cat if we_pay else idx.resolve("Interest and Dividends"),
            ),
            run_matching=False,
            commit=False,
        )
        rep.interest_transaction_id = ct_i.id
    ctx.db.add(rep)
    if principal == outstanding:
        ln.status = "settled"
    audit(ctx, "repayment", "loan", ln.id, None, {"principal": format(principal, "f"), "interest": format(interest, "f")})
    ctx.db.commit()
    ctx.db.refresh(ln)
    return _loan_out(ln)


@router.patch("/loans/{loan_id}")
def update_loan(loan_id: uuid.UUID, body: dict, ctx: Ctx = Depends(writer_ctx)):
    ln = ctx.db.get(Loan, loan_id)
    if ln is None or ln.household_id != ctx.household_id:
        raise NotFound("Loan not found")
    allowed = {"due_date", "notes", "status"}
    if set(body) - allowed:
        raise ValidationFailed("Only due_date, notes and status can be changed")
    if "status" in body and body["status"] not in ("open", "settled", "written_off"):
        raise ValidationFailed("Invalid status")
    before = snapshot(ln)
    for k, v in body.items():
        setattr(ln, k, date.fromisoformat(v) if k == "due_date" and v else v)
    audit(ctx, "update", "loan", ln.id, before, snapshot(ln))
    ctx.db.commit()
    ctx.db.refresh(ln)
    return _loan_out(ln)


# ------------------------------------------------------------ shared expenses
class ParticipantIn(Schema):
    counterparty_id: uuid.UUID | None = None  # None = you
    share_amount: OptMoney = None
    share_percent: OptMoney = None
    due_date: date | None = None


class SharedIn(Schema):
    description: str = Field(min_length=1, max_length=300)
    total_amount: Money
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    occurred_on: date
    payer_counterparty_id: uuid.UUID | None = None  # None = you paid
    split_method: str = Field(default="equal", pattern="^(equal|exact|percent)$")
    participants: list[ParticipantIn] = Field(min_length=2, max_length=50)
    transaction_id: uuid.UUID | None = None  # attach to an existing expense instead of creating one
    category_id: uuid.UUID | None = None
    merchant_name: str | None = None
    account_id: uuid.UUID | None = None
    payment_method: str | None = None

    @model_validator(mode="after")
    def _unique(self):
        ids = [p.counterparty_id for p in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("Each person can appear only once")
        return self


def compute_shares(total: Decimal, currency: str, method: str, participants: list[ParticipantIn]) -> list[Decimal]:
    """Shares always add up to the total exactly; any rounding remainder goes to the first participants."""
    exp = MINOR_UNITS.get(currency, 2)
    unit = Decimal(1).scaleb(-exp)
    n = len(participants)
    if method == "equal":
        base = (total / n).quantize(unit, rounding=ROUND_DOWN)
        shares = [base] * n
        remainder = int((total - base * n) / unit)
        for i in range(remainder):
            shares[i] += unit
        return shares
    if method == "percent":
        pcts = [p.share_percent for p in participants]
        if any(p is None or p < 0 for p in pcts) or sum(pcts) != Decimal("100"):
            raise ValidationFailed("Percentages must be given for everyone and add up to 100")
        shares = [(total * p / 100).quantize(unit, rounding=ROUND_DOWN) for p in pcts]
        remainder = int((total - sum(shares)) / unit)
        for i in range(remainder):
            shares[i % n] += unit
        return shares
    shares = [p.share_amount for p in participants]
    if any(s is None or s < 0 for s in shares):
        raise ValidationFailed("Enter an amount for every participant")
    shares = [quantize(s, currency) for s in shares]
    if sum(shares) != total:
        raise ValidationFailed(f"Shares add up to {sum(shares)}, but the bill total is {total}", code="shares_mismatch")
    return shares


def _shared_out(ctx: Ctx, s: SharedExpense) -> dict:
    names = {c.id: c.name for c in ctx.db.scalars(select(Counterparty).where(Counterparty.household_id == ctx.household_id)).all()}
    ct = ctx.db.get(CanonicalTransaction, s.transaction_id)
    parts = []
    for p in s.participants:
        parts.append(
            {
                "id": str(p.id),
                "counterparty_id": str(p.counterparty_id) if p.counterparty_id else None,
                "name": names.get(p.counterparty_id, "You") if p.counterparty_id else "You",
                "share_amount": format(quantize(p.share_amount, s.currency), "f"),
                "settled_amount": format(quantize(p.settled_amount, s.currency), "f"),
                "outstanding": format(quantize(Decimal(p.share_amount) - Decimal(p.settled_amount), s.currency), "f"),
                "due_date": p.due_date.isoformat() if p.due_date else None,
            }
        )
    return {
        "id": str(s.id),
        "transaction_id": str(s.transaction_id),
        "transaction_status": ct.status if ct else None,
        "description": s.description,
        "total_amount": format(quantize(s.total_amount, s.currency), "f"),
        "currency": s.currency,
        "occurred_on": s.occurred_on.isoformat(),
        "payer": "You" if s.payer_counterparty_id is None else names.get(s.payer_counterparty_id),
        "payer_counterparty_id": str(s.payer_counterparty_id) if s.payer_counterparty_id else None,
        "split_method": s.split_method,
        "participants": parts,
        "your_share": next((pp["share_amount"] for pp in parts if pp["counterparty_id"] is None), "0"),
    }


@router.get("/shared-expenses")
def list_shared(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(
        select(SharedExpense).options(selectinload(SharedExpense.participants)).where(SharedExpense.household_id == ctx.household_id).order_by(SharedExpense.occurred_on.desc())
    ).all()
    return [_shared_out(ctx, s) for s in rows]


@router.post("/shared-expenses", status_code=201)
def create_shared(body: SharedIn, ctx: Ctx = Depends(writer_ctx)):
    total = quantize(body.total_amount, body.currency)
    if total <= 0:
        raise ValidationFailed("Total must be greater than zero")
    for p in body.participants:
        if p.counterparty_id:
            _cp(ctx, p.counterparty_id)
    payer = _cp(ctx, body.payer_counterparty_id) if body.payer_counterparty_id else None
    if payer and not any(p.counterparty_id is None for p in body.participants):
        raise ValidationFailed("If someone else paid, include yourself as a participant")
    if payer and not any(p.counterparty_id == payer.id for p in body.participants):
        raise ValidationFailed("Include the payer as a participant")
    shares = compute_shares(total, body.currency, body.split_method, body.participants)
    your_share = next((s for p, s in zip(body.participants, shares) if p.counterparty_id is None), ZERO)
    if body.transaction_id:
        ct = ctx.db.get(CanonicalTransaction, body.transaction_id)
        if ct is None or ct.household_id != ctx.household_id:
            raise NotFound("Transaction not found")
        if ct.type != "expense" or ct.status != "active":
            raise ValidationFailed("Only active expenses can be split")
        if Decimal(ct.amount) != total:
            raise ValidationFailed(f"The expense is {ct.amount}, but the split total is {total}")
        if ctx.db.scalars(select(SharedExpense).where(SharedExpense.transaction_id == ct.id)).first():
            raise Conflict("This expense is already split", code="already_split")
    else:
        # You paid: record the full purchase once. Someone else paid: your spending is only your share.
        ct = create_transaction(
            ctx,
            TransactionIn(
                type="expense",
                occurred_on=body.occurred_on,
                description=body.description if not payer else f"{body.description} (your share; paid by {payer.name})",
                amount=total if not payer else your_share,
                currency=body.currency,
                category_id=body.category_id,
                merchant_name=body.merchant_name,
                account_id=body.account_id if not payer else None,
                payment_method=body.payment_method if not payer else None,
                counterparty_id=payer.id if payer else None,
                record_as="payment",
            ),
            commit=False,
        ) if (not payer or your_share > 0) else None
        if ct is None:
            raise ValidationFailed("Your share is zero; nothing to record")
    s = SharedExpense(
        household_id=ctx.household_id,
        transaction_id=ct.id,
        description=body.description,
        total_amount=total,
        currency=body.currency,
        occurred_on=body.occurred_on,
        payer_counterparty_id=payer.id if payer else None,
        split_method=body.split_method,
        created_by=ctx.user.id,
    )
    for p, share in zip(body.participants, shares):
        s.participants.append(SharedExpenseParticipant(household_id=ctx.household_id, counterparty_id=p.counterparty_id, share_amount=share, due_date=p.due_date))
    # The payer's own share is settled by definition.
    for part in s.participants:
        if (payer is None and part.counterparty_id is None) or (payer is not None and part.counterparty_id == payer.id):
            part.settled_amount = part.share_amount
    ctx.db.add(s)
    ctx.db.flush()
    audit(ctx, "create", "shared_expense", s.id, None, {"total": format(total, "f"), "shares": [format(x, "f") for x in shares]})
    ctx.db.commit()
    ctx.db.refresh(s)
    return _shared_out(ctx, s)


class SettleIn(Schema):
    participant_id: uuid.UUID
    amount: Money
    settled_on: date
    account_id: uuid.UUID | None = None
    payment_method: str | None = None


@router.post("/shared-expenses/{sid}/settle")
def settle(sid: uuid.UUID, body: SettleIn, ctx: Ctx = Depends(writer_ctx)):
    s = ctx.db.scalars(select(SharedExpense).options(selectinload(SharedExpense.participants)).where(SharedExpense.id == sid).with_for_update()).first()
    if s is None or s.household_id != ctx.household_id:
        raise NotFound("Shared expense not found")
    part = ctx.db.scalars(select(SharedExpenseParticipant).where(SharedExpenseParticipant.id == body.participant_id, SharedExpenseParticipant.shared_expense_id == s.id).with_for_update()).first()
    if part is None:
        raise NotFound("Participant not found")
    amount = quantize(body.amount, s.currency)
    outstanding = Decimal(part.share_amount) - Decimal(part.settled_amount)
    if amount <= 0 or amount > outstanding:
        raise ValidationFailed(f"Settlement must be between 0 and the outstanding {outstanding}", code="settlement_invalid")
    if s.payer_counterparty_id is None and part.counterparty_id is not None:
        tx_type, who, desc = "reimbursement_received", part.counterparty_id, "Reimbursement received"
    elif s.payer_counterparty_id is not None and part.counterparty_id is None:
        tx_type, who, desc = "reimbursement_paid", s.payer_counterparty_id, "Reimbursement paid"
    else:
        raise ValidationFailed("This share is settled between other people, not with you")
    person = ctx.db.get(Counterparty, who)
    ct = create_transaction(
        ctx,
        TransactionIn(
            type=tx_type,
            occurred_on=body.settled_on,
            description=f"{desc}: {s.description} ({person.name})",
            amount=amount,
            currency=s.currency,
            counterparty_id=who,
            account_id=body.account_id,
            payment_method=body.payment_method,
        ),
        run_matching=False,
        commit=False,
    )
    part.settled_amount = Decimal(part.settled_amount) + amount
    ctx.db.add(SharedExpenseSettlement(participant_id=part.id, household_id=ctx.household_id, transaction_id=ct.id, amount=amount, settled_on=body.settled_on))
    audit(ctx, "settle", "shared_expense", s.id, None, {"participant": str(part.id), "amount": format(amount, "f")})
    ctx.db.commit()
    ctx.db.refresh(s)
    return _shared_out(ctx, s)


@router.delete("/shared-expenses/{sid}")
def delete_shared(sid: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    s = ctx.db.scalars(select(SharedExpense).options(selectinload(SharedExpense.participants)).where(SharedExpense.id == sid)).first()
    if s is None or s.household_id != ctx.household_id:
        raise NotFound("Shared expense not found")
    if any(Decimal(p.settled_amount) > 0 and not ((s.payer_counterparty_id is None and p.counterparty_id is None) or p.counterparty_id == s.payer_counterparty_id) for p in s.participants):
        raise Conflict("Settlements have been recorded; void those first", code="has_settlements")
    audit(ctx, "delete", "shared_expense", s.id, {"description": s.description}, None)
    ctx.db.delete(s)
    ctx.db.commit()
    return {"ok": True}

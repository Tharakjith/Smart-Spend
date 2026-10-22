"""Credit card bills.

Money rules (unchanged from the ledger): card purchases count as spending on the day they are made; paying the
card bill is an internal transfer (credit_card_payment) and never counts as spending. Interest and fees are the
only bill-related spending, recorded as expenses when the user chooses to. A bill's paid / remaining / overdue
state is always derived from linked payments, never typed in.
"""
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select

from app.core.deps import Ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import fmt, quantize
from app.models import Account, CanonicalTransaction, CreditCardBillPayment, CreditCardStatement
from app.models.finance import TRANSACTION_TYPES

ZERO = Decimal("0")
CT = CanonicalTransaction
PAYMENT_TYPES = ("credit_card_payment", "transfer")
CC_TEXT = re.compile(r"credit\s*card|\bcc\b|card\s*(bill|payment)|autopay", re.I)


def get_card(ctx: Ctx, account_id: uuid.UUID) -> Account:
    acc = ctx.db.get(Account, account_id)
    if acc is None or acc.household_id != ctx.household_id:
        raise NotFound("Card not found")
    if acc.type != "credit_card":
        raise ValidationFailed("This account is not a credit card", code="not_a_credit_card")
    return acc


def balance_as_of(ctx: Ctx, acc: Account, as_of: date | None = None, exclude_ids: set | None = None) -> Decimal:
    """Signed balance (negative = amount owed on a card) from the opening balance and active ledger movements."""
    total = Decimal(acc.opening_balance or 0)
    q = select(CT.type, CT.cash_amount, CT.account_id, CT.to_account_id).where(
        CT.household_id == ctx.household_id, CT.status == "active", CT.currency == acc.currency, or_(CT.account_id == acc.id, CT.to_account_id == acc.id)
    )
    if exclude_ids:
        q = q.where(CT.id.not_in(exclude_ids))
    if acc.opening_balance_date:
        q = q.where(CT.occurred_on >= acc.opening_balance_date)
    if as_of:
        q = q.where(CT.occurred_on <= as_of)
    for typ, cash, account_id, to_account_id in ctx.db.execute(q).all():
        cash = Decimal(cash)
        direction = TRANSACTION_TYPES[typ]
        if account_id == acc.id:
            total += cash if direction == "in" else -cash
        if to_account_id == acc.id and typ in PAYMENT_TYPES:
            total += cash
    return quantize(total, acc.currency)


def last_statement(ctx: Ctx, acc: Account) -> CreditCardStatement | None:
    return ctx.db.scalars(
        select(CreditCardStatement).where(CreditCardStatement.account_id == acc.id).order_by(CreditCardStatement.statement_date.desc())
    ).first()


def _month_day(year: int, month: int, day: int) -> date:
    import calendar

    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_statement_date(acc: Account, after: date) -> date | None:
    if not acc.statement_day:
        return None
    d = _month_day(after.year, after.month, acc.statement_day)
    if d <= after:
        y, m = (after.year + (after.month == 12), after.month % 12 + 1)
        d = _month_day(y, m, acc.statement_day)
    return d


def default_due_date(acc: Account, statement_date: date) -> date | None:
    if not acc.due_day:
        return None
    d = _month_day(statement_date.year, statement_date.month, acc.due_day)
    if d <= statement_date:
        y, m = (statement_date.year + (statement_date.month == 12), statement_date.month % 12 + 1)
        d = _month_day(y, m, acc.due_day)
    return d


def payment_links(ctx: Ctx, statement: CreditCardStatement) -> list[tuple[CreditCardBillPayment, CanonicalTransaction]]:
    return list(
        ctx.db.execute(
            select(CreditCardBillPayment, CT)
            .join(CT, CT.id == CreditCardBillPayment.transaction_id)
            .where(CreditCardBillPayment.statement_id == statement.id)
            .order_by(CT.occurred_on)
        ).all()
    )


def linked_elsewhere(ctx: Ctx, tx_id: uuid.UUID, exclude_statement: uuid.UUID | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(CreditCardBillPayment.amount), 0)).where(CreditCardBillPayment.transaction_id == tx_id)
    if exclude_statement:
        q = q.where(CreditCardBillPayment.statement_id != exclude_statement)
    return Decimal(ctx.db.scalar(q) or 0)


def statement_state(ctx: Ctx, s: CreditCardStatement, today: date | None = None) -> dict:
    today = today or date.today()
    links = payment_links(ctx, s)
    active = [(link, t) for link, t in links if t.status == "active"]
    paid = sum((Decimal(link.amount) for link, _ in active), ZERO)
    paid_by_due = sum((Decimal(link.amount) for link, t in active if t.occurred_on <= s.due_date), ZERO)
    total, minimum = Decimal(s.total_due), Decimal(s.minimum_due)
    remaining = max(total - paid, ZERO)
    min_remaining = max(minimum - paid, ZERO)
    if total == 0:
        status = "no_dues"
    elif paid >= total:
        status = "paid"
    elif today > s.due_date and paid < (minimum if minimum > 0 else total):
        status = "overdue"
    elif paid >= minimum and minimum > 0:
        status = "minimum_paid"
    elif paid > 0:
        status = "partially_paid"
    else:
        status = "unpaid"
    return {
        "paid_amount": format(quantize(paid, s.currency), "f"),
        "remaining_amount": format(quantize(remaining, s.currency), "f"),
        "minimum_remaining": format(quantize(min_remaining, s.currency), "f"),
        "status": status,
        "days_until_due": (s.due_date - today).days,
        "paid_late": total > 0 and today > s.due_date and paid_by_due < minimum,
        # Paying less than the full amount by the due date usually means interest on the next statement.
        "interest_may_apply": total > 0 and paid_by_due < total and (today > s.due_date or paid >= total),
    }


def serialize_statement(ctx: Ctx, s: CreditCardStatement, detail: bool = False) -> dict:
    out = {
        "id": str(s.id),
        "account_id": str(s.account_id),
        "period_start": s.period_start.isoformat(),
        "statement_date": s.statement_date.isoformat(),
        "due_date": s.due_date.isoformat(),
        "total_due": format(quantize(s.total_due, s.currency), "f"),
        "minimum_due": format(quantize(s.minimum_due, s.currency), "f"),
        "interest_charged": format(quantize(s.interest_charged, s.currency), "f"),
        "fees_charged": format(quantize(s.fees_charged, s.currency), "f"),
        "currency": s.currency,
        "document_id": str(s.document_id) if s.document_id else None,
        "notes": s.notes,
        **statement_state(ctx, s),
    }
    if detail:
        out["payments"] = [
            {
                "link_id": str(link.id),
                "transaction_id": str(t.id),
                "occurred_on": t.occurred_on.isoformat(),
                "description": t.description,
                "amount": format(quantize(link.amount, s.currency), "f"),
                "transaction_amount": format(quantize(t.amount, s.currency), "f"),
                "status": t.status,
                "on_time": t.occurred_on <= s.due_date,
            }
            for link, t in payment_links(ctx, s)
        ]
        acc = ctx.db.get(Account, s.account_id)
        # Payments of this bill settle it; they are not part of the cycle the bill describes.
        own_payments = {t.id for _, t in payment_links(ctx, s)}
        out["cycle"] = cycle_summary(ctx, acc, s.period_start, s.statement_date, exclude_ids=own_payments)
        out["charge_transaction_ids"] = s.charge_transaction_ids
        out["payment_suggestions"] = payment_suggestions(ctx, acc, s)
    return out


def cycle_summary(ctx: Ctx, acc: Account, start: date, end: date, exclude_ids: set | None = None) -> dict:
    """What happened on the card between two dates; the computed closing balance is a deterministic sum."""
    exclude_ids = exclude_ids or set()
    txs = ctx.db.scalars(
        select(CT)
        .where(CT.household_id == ctx.household_id, CT.status == "active", or_(CT.account_id == acc.id, CT.to_account_id == acc.id), CT.occurred_on >= start, CT.occurred_on <= end)
        .order_by(CT.occurred_on, CT.created_at)
    ).all()
    txs = [t for t in txs if t.id not in exclude_ids]
    purchases = credits = payments = ZERO
    rows = []
    for t in txs:
        cash = Decimal(t.cash_amount)
        if t.to_account_id == acc.id and t.type in PAYMENT_TYPES:
            kind, payments = "payment", payments + cash
        elif TRANSACTION_TYPES[t.type] == "in":
            kind, credits = "credit", credits + cash
        else:
            kind, purchases = "purchase", purchases + cash
        rows.append({"id": str(t.id), "occurred_on": t.occurred_on.isoformat(), "description": t.description, "type": t.type, "kind": kind, "amount": format(quantize(cash, acc.currency), "f")})
    opening_owed = -balance_as_of(ctx, acc, start - timedelta(days=1), exclude_ids)
    closing_owed = -balance_as_of(ctx, acc, end, exclude_ids)
    q = lambda v: format(quantize(v, acc.currency), "f")  # noqa: E731
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "previous_balance": q(max(opening_owed, ZERO)),
        "purchases": q(purchases),
        "credits": q(credits),
        "payments": q(payments),
        "computed_total_due": q(max(closing_owed, ZERO)),
        "transactions": rows,
    }


def payment_suggestions(ctx: Ctx, acc: Account, s: CreditCardStatement) -> list[dict]:
    """Unlinked card payments that probably settle this bill (e.g. a 'CC PAYMENT XXXX9912' bank row)."""
    window_start, window_end = s.statement_date - timedelta(days=5), s.due_date + timedelta(days=30)
    candidates = ctx.db.scalars(
        select(CT).where(
            CT.household_id == ctx.household_id,
            CT.status == "active",
            CT.type.in_(PAYMENT_TYPES),
            CT.currency == s.currency,
            CT.occurred_on <= window_end,
            or_(
                # Payments already made to this card (including an earlier overpayment's unlinked remainder).
                and_(CT.to_account_id == acc.id, CT.occurred_on >= s.period_start - timedelta(days=45)),
                # Bank rows that only know one side of the transfer: keep to the bill's payment window.
                and_(CT.to_account_id.is_(None), CT.occurred_on >= window_start),
            ),
            CT.account_id.is_distinct_from(acc.id),
        )
    ).all()
    already = {t.id for _, t in payment_links(ctx, s)}
    remaining = Decimal(statement_state(ctx, s)["remaining_amount"])
    out = []
    for t in candidates:
        if t.id in already:
            continue
        available = Decimal(t.amount) - linked_elsewhere(ctx, t.id)
        if available <= 0:
            continue
        reasons = []
        if t.to_account_id == acc.id:
            reasons.append("Paid to this card")
        elif acc.masked_number and acc.masked_number in (t.description or ""):
            reasons.append(f"Description mentions card ending {acc.masked_number}")
        elif CC_TEXT.search(t.description or ""):
            reasons.append("Description looks like a credit card payment")
        else:
            continue
        if available == remaining:
            reasons.append("Amount equals the remaining bill")
        elif available == Decimal(s.minimum_due):
            reasons.append("Amount equals the minimum due")
        out.append(
            {"transaction_id": str(t.id), "occurred_on": t.occurred_on.isoformat(), "description": t.description, "amount": format(quantize(t.amount, s.currency), "f"), "available": format(quantize(available, s.currency), "f"), "reasons": reasons}
        )
    return sorted(out, key=lambda x: (len(x["reasons"]) * -1, abs((date.fromisoformat(x["occurred_on"]) - s.due_date).days)))


def card_summary(ctx: Ctx, acc: Account, today: date | None = None) -> dict:
    today = today or date.today()
    balance = balance_as_of(ctx, acc)
    outstanding = max(-balance, ZERO)
    credit_balance = max(balance, ZERO)
    last = last_statement(ctx, acc)
    unbilled_from = (last.statement_date + timedelta(days=1)) if last else (acc.opening_balance_date or date(1970, 1, 1))
    unbilled = ZERO
    for typ, cash in ctx.db.execute(
        select(CT.type, CT.cash_amount).where(
            CT.household_id == ctx.household_id, CT.status == "active", CT.account_id == acc.id, CT.occurred_on >= unbilled_from, CT.occurred_on <= today
        )
    ).all():
        unbilled += Decimal(cash) if TRANSACTION_TYPES[typ] != "in" else -Decimal(cash)
    limit = Decimal(acc.credit_limit) if acc.credit_limit is not None else None
    next_stmt = next_statement_date(acc, last.statement_date if last else today - timedelta(days=1))
    q = lambda v: None if v is None else format(quantize(v, acc.currency), "f")  # noqa: E731
    return {
        "account_id": str(acc.id),
        "name": acc.name,
        "institution": acc.institution,
        "masked_number": acc.masked_number,
        "currency": acc.currency,
        "credit_limit": q(limit),
        "statement_day": acc.statement_day,
        "due_day": acc.due_day,
        "outstanding": q(outstanding),
        "credit_balance": q(credit_balance),
        "available_credit": q(max(limit - outstanding, ZERO)) if limit is not None else None,
        "utilization_pct": round(float(outstanding / limit * 100), 1) if limit else None,
        "unbilled_amount": q(max(unbilled, ZERO)),
        "next_statement_date": next_stmt.isoformat() if next_stmt else None,
        "last_statement": serialize_statement(ctx, last) if last else None,
    }


def create_payment_link(ctx: Ctx, s: CreditCardStatement, acc: Account, t: CanonicalTransaction, amount: Decimal | None) -> CreditCardBillPayment:
    if t.household_id != ctx.household_id or t.status != "active":
        raise NotFound("Payment transaction not found")
    if t.type not in PAYMENT_TYPES:
        raise ValidationFailed("Only credit card payments or transfers to the card can settle a card bill", code="not_a_card_payment")
    if t.to_account_id not in (None, acc.id):
        raise ValidationFailed("This payment went to a different account", code="wrong_card")
    if t.account_id == acc.id:
        raise ValidationFailed("A payment from the card itself can't settle its bill", code="wrong_card")
    if t.currency != s.currency:
        raise ValidationFailed("Payment and bill currencies differ", code="currency_mismatch")
    if ctx.db.scalars(select(CreditCardBillPayment).where(CreditCardBillPayment.statement_id == s.id, CreditCardBillPayment.transaction_id == t.id)).first():
        raise Conflict("This payment is already linked to this bill", code="already_linked")
    available = Decimal(t.amount) - linked_elsewhere(ctx, t.id)
    if available <= 0:
        raise Conflict("This payment is already fully linked to other bills", code="payment_fully_linked")
    remaining = Decimal(statement_state(ctx, s)["remaining_amount"])
    if amount is None:
        amount = min(available, remaining) if remaining > 0 else available
    amount = quantize(amount, s.currency)
    if amount <= 0:
        raise ValidationFailed("Amount must be greater than zero")
    if amount > available:
        raise Conflict(f"Only {fmt(available, s.currency)} of this payment is still unlinked", code="exceeds_payment", details={"available": format(available, "f")})
    if t.to_account_id is None:
        t.to_account_id = acc.id  # an imported bank row only knew one side of the transfer
        t.version += 1
    link = CreditCardBillPayment(household_id=ctx.household_id, statement_id=s.id, transaction_id=t.id, amount=amount, created_by=ctx.user.id)
    ctx.db.add(link)
    ctx.db.flush()
    return link

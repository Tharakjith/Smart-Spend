"""Budgets, savings goals and recurring expenses. Recurring items are predictions until a real
transaction is linked with mark-paid; they never affect totals on their own."""
import statistics
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select

from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import quantize
from app.models import Budget, CanonicalTransaction, Category, Merchant, RecurringExpense, SavingsGoal
from app.modules.analytics.service import budget_status
from app.modules.common import Money, OptMoney, Schema, audit, snapshot

router = APIRouter(tags=["planning"])


def _own(ctx: Ctx, model, oid, label):
    o = ctx.db.get(model, oid)
    if o is None or o.household_id != ctx.household_id:
        raise NotFound(f"{label} not found")
    return o


# ------------------------------------------------------------ budgets
class BudgetIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    period: str = Field(default="monthly", pattern="^(monthly|weekly)$")
    category_id: uuid.UUID | None = None
    amount: Money
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    alert_threshold_pct: int = Field(default=80, ge=1, le=100)
    is_active: bool = True


def _budget_out(b: Budget) -> dict:
    return {
        "id": str(b.id),
        "name": b.name,
        "period": b.period,
        "category_id": str(b.category_id) if b.category_id else None,
        "amount": format(Decimal(b.amount), "f"),
        "currency": b.currency,
        "alert_threshold_pct": b.alert_threshold_pct,
        "is_active": b.is_active,
    }


@router.get("/budgets")
def list_budgets(ctx: Ctx = Depends(get_ctx)):
    return [_budget_out(b) for b in ctx.db.scalars(select(Budget).where(Budget.household_id == ctx.household_id).order_by(Budget.name)).all()]


@router.get("/budgets/status")
def status(ctx: Ctx = Depends(get_ctx), on: date | None = None):
    return budget_status(ctx.db, ctx.household_id, ctx.household.base_currency, on)


@router.post("/budgets", status_code=201)
def create_budget(body: BudgetIn, ctx: Ctx = Depends(writer_ctx)):
    if body.amount <= 0:
        raise ValidationFailed("Budget amount must be greater than zero")
    if body.category_id:
        _own(ctx, Category, body.category_id, "Category")
    cur = body.currency or ctx.household.base_currency
    b = Budget(household_id=ctx.household_id, **{**body.model_dump(), "currency": cur, "amount": quantize(body.amount, cur)})
    ctx.db.add(b)
    ctx.db.flush()
    audit(ctx, "create", "budget", b.id, None, snapshot(b))
    ctx.db.commit()
    return _budget_out(b)


@router.put("/budgets/{bid}")
def update_budget(bid: uuid.UUID, body: BudgetIn, ctx: Ctx = Depends(writer_ctx)):
    b = _own(ctx, Budget, bid, "Budget")
    if body.amount <= 0:
        raise ValidationFailed("Budget amount must be greater than zero")
    before = snapshot(b)
    for k, v in body.model_dump().items():
        if k == "currency" and v is None:
            continue
        setattr(b, k, v)
    audit(ctx, "update", "budget", b.id, before, snapshot(b))
    ctx.db.commit()
    return _budget_out(b)


@router.delete("/budgets/{bid}")
def delete_budget(bid: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    b = _own(ctx, Budget, bid, "Budget")
    audit(ctx, "delete", "budget", b.id, snapshot(b), None)
    ctx.db.delete(b)
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------ savings goals
class GoalIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Money
    saved_amount: Money = Decimal("0")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_date: date | None = None
    status: str = Field(default="active", pattern="^(active|achieved|paused)$")


def _goal_out(g: SavingsGoal) -> dict:
    target, saved = Decimal(g.target_amount), Decimal(g.saved_amount)
    months_left = None
    monthly_needed = None
    if g.target_date and saved < target:
        months_left = max(1, (g.target_date.year - date.today().year) * 12 + g.target_date.month - date.today().month)
        monthly_needed = format(quantize((target - saved) / months_left, g.currency), "f")
    return {
        "id": str(g.id),
        "name": g.name,
        "target_amount": format(quantize(target, g.currency), "f"),
        "saved_amount": format(quantize(saved, g.currency), "f"),
        "remaining": format(quantize(max(target - saved, Decimal("0")), g.currency), "f"),
        "percent": round(float(saved / target * 100), 1) if target else 0,
        "currency": g.currency,
        "target_date": g.target_date.isoformat() if g.target_date else None,
        "monthly_needed": monthly_needed,
        "status": g.status,
    }


@router.get("/savings-goals")
def list_goals(ctx: Ctx = Depends(get_ctx)):
    return [_goal_out(g) for g in ctx.db.scalars(select(SavingsGoal).where(SavingsGoal.household_id == ctx.household_id).order_by(SavingsGoal.created_at)).all()]


@router.post("/savings-goals", status_code=201)
def create_goal(body: GoalIn, ctx: Ctx = Depends(writer_ctx)):
    if body.target_amount <= 0 or body.saved_amount < 0:
        raise ValidationFailed("Target must be positive and saved amount non-negative")
    g = SavingsGoal(household_id=ctx.household_id, **{**body.model_dump(), "currency": body.currency or ctx.household.base_currency})
    ctx.db.add(g)
    ctx.db.flush()
    audit(ctx, "create", "savings_goal", g.id, None, snapshot(g))
    ctx.db.commit()
    return _goal_out(g)


@router.put("/savings-goals/{gid}")
def update_goal(gid: uuid.UUID, body: GoalIn, ctx: Ctx = Depends(writer_ctx)):
    g = _own(ctx, SavingsGoal, gid, "Goal")
    before = snapshot(g)
    for k, v in body.model_dump().items():
        if k == "currency" and v is None:
            continue
        setattr(g, k, v)
    if Decimal(g.saved_amount) >= Decimal(g.target_amount) and g.status == "active":
        g.status = "achieved"
    audit(ctx, "update", "savings_goal", g.id, before, snapshot(g))
    ctx.db.commit()
    return _goal_out(g)


@router.delete("/savings-goals/{gid}")
def delete_goal(gid: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    g = _own(ctx, SavingsGoal, gid, "Goal")
    ctx.db.delete(g)
    audit(ctx, "delete", "savings_goal", gid)
    ctx.db.commit()
    return {"ok": True}


# ------------------------------------------------------------ recurring
STEP = {"weekly": relativedelta(weeks=1), "monthly": relativedelta(months=1), "quarterly": relativedelta(months=3), "yearly": relativedelta(years=1)}


class RecurringIn(Schema):
    name: str = Field(min_length=1, max_length=160)
    amount: Money
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    category_id: uuid.UUID | None = None
    merchant_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None
    frequency: str = Field(pattern="^(weekly|monthly|quarterly|yearly)$")
    next_due_date: date
    is_subscription: bool = False
    status: str = Field(default="active", pattern="^(active|paused|suggested|cancelled)$")
    remind_days_before: int = Field(default=3, ge=0, le=30)
    notes: str = Field(default="", max_length=1000)


def _rec_out(ctx: Ctx, r: RecurringExpense) -> dict:
    m = ctx.db.get(Merchant, r.merchant_id) if r.merchant_id else None
    return {
        "id": str(r.id),
        "name": r.name,
        "amount": format(Decimal(r.amount), "f"),
        "currency": r.currency,
        "category_id": str(r.category_id) if r.category_id else None,
        "merchant_id": str(r.merchant_id) if r.merchant_id else None,
        "merchant_name": m.name if m else None,
        "frequency": r.frequency,
        "next_due_date": r.next_due_date.isoformat(),
        "is_subscription": r.is_subscription,
        "status": r.status,
        "detected": r.detected,
        "remind_days_before": r.remind_days_before,
        "last_transaction_id": str(r.last_transaction_id) if r.last_transaction_id else None,
        "notes": r.notes,
        "monthly_equivalent": format(quantize(Decimal(r.amount) * {"weekly": Decimal("52") / 12, "monthly": 1, "quarterly": Decimal(1) / 3, "yearly": Decimal(1) / 12}[r.frequency], r.currency), "f"),
    }


@router.get("/recurring")
def list_recurring(ctx: Ctx = Depends(get_ctx), status: str | None = None):
    q = select(RecurringExpense).where(RecurringExpense.household_id == ctx.household_id).order_by(RecurringExpense.next_due_date)
    if status:
        q = q.where(RecurringExpense.status.in_(status.split(",")))
    return [_rec_out(ctx, r) for r in ctx.db.scalars(q).all()]


@router.get("/recurring/upcoming")
def upcoming(ctx: Ctx = Depends(get_ctx), days: int = Query(30, le=365)):
    out = []
    until = date.today() + timedelta(days=days)
    for r in ctx.db.scalars(select(RecurringExpense).where(RecurringExpense.household_id == ctx.household_id, RecurringExpense.status == "active")).all():
        d = r.next_due_date
        while d <= until:
            out.append({"recurring_id": str(r.id), "name": r.name, "due_date": d.isoformat(), "amount": format(Decimal(r.amount), "f"), "currency": r.currency, "predicted": True})
            d = d + STEP[r.frequency]
    return sorted(out, key=lambda x: x["due_date"])


@router.post("/recurring", status_code=201)
def create_recurring(body: RecurringIn, ctx: Ctx = Depends(writer_ctx)):
    if body.amount <= 0:
        raise ValidationFailed("Amount must be greater than zero")
    r = RecurringExpense(household_id=ctx.household_id, **{**body.model_dump(), "currency": body.currency or ctx.household.base_currency})
    ctx.db.add(r)
    ctx.db.flush()
    audit(ctx, "create", "recurring", r.id, None, snapshot(r))
    ctx.db.commit()
    return _rec_out(ctx, r)


@router.put("/recurring/{rid}")
def update_recurring(rid: uuid.UUID, body: RecurringIn, ctx: Ctx = Depends(writer_ctx)):
    r = _own(ctx, RecurringExpense, rid, "Recurring expense")
    before = snapshot(r)
    for k, v in body.model_dump().items():
        if k == "currency" and v is None:
            continue
        setattr(r, k, v)
    audit(ctx, "update", "recurring", r.id, before, snapshot(r))
    ctx.db.commit()
    return _rec_out(ctx, r)


@router.delete("/recurring/{rid}")
def delete_recurring(rid: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    r = _own(ctx, RecurringExpense, rid, "Recurring expense")
    ctx.db.delete(r)
    audit(ctx, "delete", "recurring", rid)
    ctx.db.commit()
    return {"ok": True}


class MarkPaidIn(Schema):
    transaction_id: uuid.UUID


@router.post("/recurring/{rid}/mark-paid")
def mark_paid(rid: uuid.UUID, body: MarkPaidIn, ctx: Ctx = Depends(writer_ctx)):
    """Links the actual transaction (the prediction becomes real only through it) and advances the schedule."""
    r = _own(ctx, RecurringExpense, rid, "Recurring expense")
    ct = _own(ctx, CanonicalTransaction, body.transaction_id, "Transaction")
    if ct.status != "active":
        raise Conflict("Pick an active transaction")
    r.last_transaction_id = ct.id
    ct.is_recurring = True
    nxt = r.next_due_date
    while nxt <= ct.occurred_on:
        nxt = nxt + STEP[r.frequency]
    r.next_due_date = nxt
    if r.status == "suggested":
        r.status = "active"
    audit(ctx, "mark_paid", "recurring", r.id, None, {"transaction_id": str(ct.id), "next_due_date": nxt.isoformat()})
    ctx.db.commit()
    return _rec_out(ctx, r)


@router.post("/recurring/detect")
def detect(ctx: Ctx = Depends(writer_ctx)):
    """Suggests recurring expenses: same merchant, ≥3 occurrences at a regular interval with stable amounts."""
    since = date.today() - timedelta(days=400)
    txs = ctx.db.scalars(
        select(CanonicalTransaction).where(
            CanonicalTransaction.household_id == ctx.household_id,
            CanonicalTransaction.status == "active",
            CanonicalTransaction.type == "expense",
            CanonicalTransaction.merchant_id.is_not(None),
            CanonicalTransaction.occurred_on >= since,
        )
    ).all()
    groups = defaultdict(list)
    for t in txs:
        groups[(t.merchant_id, t.currency)].append(t)
    existing = {r.merchant_id for r in ctx.db.scalars(select(RecurringExpense).where(RecurringExpense.household_id == ctx.household_id)).all()}
    created = []
    for (mid, cur), items in groups.items():
        if mid in existing or len(items) < 3:
            continue
        items.sort(key=lambda t: t.occurred_on)
        gaps = [(b.occurred_on - a.occurred_on).days for a, b in zip(items, items[1:])]
        med_gap = statistics.median(gaps)
        freq = "weekly" if 5 <= med_gap <= 9 else "monthly" if 26 <= med_gap <= 35 else "quarterly" if 85 <= med_gap <= 95 else "yearly" if 355 <= med_gap <= 375 else None
        if not freq or any(abs(g - med_gap) > max(4, med_gap * 0.2) for g in gaps):
            continue
        amounts = [Decimal(t.amount) for t in items]
        med_amt = Decimal(str(statistics.median(amounts)))
        if any(abs(a - med_amt) > med_amt * Decimal("0.15") for a in amounts):
            continue
        last = items[-1]
        nxt = last.occurred_on + STEP[freq]
        m = ctx.db.get(Merchant, mid)
        cat = ctx.db.get(Category, last.category_id) if last.category_id else None
        r = RecurringExpense(
            household_id=ctx.household_id,
            name=m.name,
            amount=quantize(med_amt, cur),
            currency=cur,
            category_id=last.category_id,
            merchant_id=mid,
            frequency=freq,
            next_due_date=nxt,
            is_subscription=bool(cat and "subscription" in cat.name.lower()),
            status="suggested",
            detected=True,
            last_transaction_id=last.id,
        )
        ctx.db.add(r)
        ctx.db.flush()
        created.append(_rec_out(ctx, r))
    ctx.db.commit()
    return {"suggested": created}

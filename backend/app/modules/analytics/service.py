"""Financial calculations. Every figure is computed from canonical transactions using the rules in
docs/ARCHITECTURE.md §5. Merged/voided/reversed records contribute nothing; payments absorbed by bills
contribute only their unallocated remainder (effective_amount)."""
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import Ctx
from app.core.money import quantize
from app.models import (
    Budget,
    CanonicalTransaction,
    Category,
    Counterparty,
    Document,
    Loan,
    LoanRepayment,
    Merchant,
    RecurringExpense,
    ReconciliationMatch,
    SharedExpense,
    SharedExpenseParticipant,
)
from app.modules.categories.service import CategoryIndex

ZERO = Decimal("0")
CT = CanonicalTransaction


def month_bounds(month: str | None) -> tuple[date, date]:
    """[start, end) for 'YYYY-MM' (defaults to the current month)."""
    if month:
        y, m = (int(x) for x in month.split("-"))
    else:
        t = date.today()
        y, m = t.year, t.month
    start = date(y, m, 1)
    end = date(y + (m == 12), (m % 12) + 1, 1)
    return start, end


def prev_month(start: date) -> str:
    d = start - timedelta(days=1)
    return f"{d.year:04d}-{d.month:02d}"


def _sum(db: Session, hid, start, end, currency, types, col=CT.effective_amount) -> Decimal:
    v = db.scalar(
        select(func.coalesce(func.sum(col), 0)).where(
            CT.household_id == hid, CT.status == "active", CT.currency == currency, CT.type.in_(types), CT.occurred_on >= start, CT.occurred_on < end
        )
    )
    return Decimal(v or 0)


def others_share_paid_by_self(db: Session, hid, start, end, currency) -> Decimal:
    """Portion of shared bills the household paid that belongs to other people."""
    v = db.scalar(
        select(func.coalesce(func.sum(SharedExpenseParticipant.share_amount), 0))
        .join(SharedExpense, SharedExpense.id == SharedExpenseParticipant.shared_expense_id)
        .join(CT, CT.id == SharedExpense.transaction_id)
        .where(
            SharedExpense.household_id == hid,
            SharedExpense.payer_counterparty_id.is_(None),
            SharedExpenseParticipant.counterparty_id.is_not(None),
            CT.status == "active",
            CT.currency == currency,
            CT.occurred_on >= start,
            CT.occurred_on < end,
        )
    )
    return Decimal(v or 0)


def period_totals(db: Session, hid, start: date, end: date, currency: str) -> dict:
    gross = _sum(db, hid, start, end, currency, ["expense"])
    refunds = _sum(db, hid, start, end, currency, ["refund"])
    net = gross - refunds
    others = others_share_paid_by_self(db, hid, start, end, currency)
    income = _sum(db, hid, start, end, currency, ["income"])
    reimb_in = _sum(db, hid, start, end, currency, ["reimbursement_received"], CT.cash_amount)
    reimb_out = _sum(db, hid, start, end, currency, ["reimbursement_paid"], CT.cash_amount)
    loans_given = _sum(db, hid, start, end, currency, ["loan_given"], CT.cash_amount)
    loans_received = _sum(db, hid, start, end, currency, ["loan_received"], CT.cash_amount)
    rep_paid = _sum(db, hid, start, end, currency, ["loan_repayment_paid"], CT.cash_amount)
    rep_recv = _sum(db, hid, start, end, currency, ["loan_repayment_received"], CT.cash_amount)
    transfers = _sum(db, hid, start, end, currency, ["transfer", "credit_card_payment"], CT.cash_amount)
    spend_cash = _sum(db, hid, start, end, currency, ["expense"], CT.cash_amount)
    refund_cash = _sum(db, hid, start, end, currency, ["refund"], CT.cash_amount)
    income_cash = _sum(db, hid, start, end, currency, ["income"], CT.cash_amount)
    inflow = income_cash + refund_cash + reimb_in + loans_received + rep_recv
    outflow = spend_cash + reimb_out + loans_given + rep_paid
    q = lambda v: format(quantize(v, currency), "f")  # noqa: E731
    return {
        "currency": currency,
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "gross_spending": q(gross),
        "refunds": q(refunds),
        "net_spending": q(net),
        "others_share_of_shared_bills": q(others),
        "personal_spending": q(net - others),
        "income": q(income),
        "reimbursements_received": q(reimb_in),
        "reimbursements_paid": q(reimb_out),
        "loans_given": q(loans_given),
        "loans_received": q(loans_received),
        "loan_repayments_paid": q(rep_paid),
        "loan_repayments_received": q(rep_recv),
        "internal_transfers": q(transfers),
        "cash_inflow": q(inflow),
        "cash_outflow": q(outflow),
        "net_cash_flow": q(inflow - outflow),
        "estimated_savings": q(income - (net - others)),
    }


def other_currency_spending(db: Session, hid, start, end, base: str) -> list[dict]:
    rows = db.execute(
        select(CT.currency, func.sum(CT.effective_amount))
        .where(CT.household_id == hid, CT.status == "active", CT.type == "expense", CT.currency != base, CT.occurred_on >= start, CT.occurred_on < end)
        .group_by(CT.currency)
    ).all()
    return [{"currency": c, "gross_spending": format(quantize(v, c), "f")} for c, v in rows]


def loan_balances(db: Session, hid, currency: str) -> dict:
    loans = db.scalars(select(Loan).options(selectinload(Loan.repayments)).where(Loan.household_id == hid, Loan.status == "open", Loan.currency == currency)).all()
    recv = pay = ZERO
    for ln in loans:
        outstanding = Decimal(ln.principal) - sum((Decimal(r.principal_amount) for r in ln.repayments), ZERO)
        if ln.direction == "given":
            recv += max(outstanding, ZERO)
        else:
            pay += max(outstanding, ZERO)
    return {"receivable": format(recv, "f"), "payable": format(pay, "f")}


def shared_balances(db: Session, hid, currency: str) -> dict:
    rows = db.execute(
        select(SharedExpense.payer_counterparty_id, SharedExpenseParticipant.counterparty_id, SharedExpenseParticipant.share_amount, SharedExpenseParticipant.settled_amount)
        .join(SharedExpense, SharedExpense.id == SharedExpenseParticipant.shared_expense_id)
        .join(CT, CT.id == SharedExpense.transaction_id)
        .where(SharedExpense.household_id == hid, SharedExpense.currency == currency, CT.status == "active")
    ).all()
    recv = pay = ZERO
    for payer, participant, share, settled in rows:
        open_amt = Decimal(share) - Decimal(settled)
        if payer is None and participant is not None:
            recv += open_amt  # someone owes us their share
        elif payer is not None and participant is None:
            pay += open_amt  # we owe the payer our share
    return {"receivable": format(recv, "f"), "payable": format(pay, "f")}


def budget_status(db: Session, hid, currency: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    idx = CategoryIndex(db, hid)
    out = []
    for b in db.scalars(select(Budget).where(Budget.household_id == hid, Budget.is_active.is_(True))).all():
        if b.period == "monthly":
            start, end = month_bounds(f"{today.year:04d}-{today.month:02d}")
        else:
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=7)
        q = select(func.coalesce(func.sum(CT.effective_amount), 0)).where(
            CT.household_id == hid, CT.status == "active", CT.type == "expense", CT.currency == b.currency, CT.occurred_on >= start, CT.occurred_on < end
        )
        rq = select(func.coalesce(func.sum(CT.effective_amount), 0)).where(
            CT.household_id == hid, CT.status == "active", CT.type == "refund", CT.currency == b.currency, CT.occurred_on >= start, CT.occurred_on < end
        )
        if b.category_id:
            ids = idx.subtree(b.category_id)
            q = q.where(CT.category_id.in_(ids))
            rq = rq.where(CT.category_id.in_(ids))
        spent = Decimal(db.scalar(q) or 0) - Decimal(db.scalar(rq) or 0)
        spent = max(spent, ZERO)
        amount = Decimal(b.amount)
        pct = float(spent / amount * 100) if amount else 0.0
        out.append(
            {
                "budget_id": str(b.id),
                "name": b.name,
                "period": b.period,
                "category_id": str(b.category_id) if b.category_id else None,
                "category_name": idx.by_id[b.category_id].name if b.category_id in idx.by_id else None,
                "amount": format(quantize(amount, b.currency), "f"),
                "spent": format(quantize(spent, b.currency), "f"),
                "remaining": format(quantize(amount - spent, b.currency), "f"),
                "percent_used": round(pct, 1),
                "alert_threshold_pct": b.alert_threshold_pct,
                "state": "over" if spent > amount else "warning" if pct >= b.alert_threshold_pct else "ok",
                "period_start": start.isoformat(),
                "period_end_exclusive": end.isoformat(),
                "currency": b.currency,
            }
        )
    return out


def dashboard(ctx: Ctx, month: str | None) -> dict:
    db, hid, cur = ctx.db, ctx.household_id, ctx.household.base_currency
    start, end = month_bounds(month)
    this = period_totals(db, hid, start, end, cur)
    pstart, pend = month_bounds(prev_month(start))
    prev = period_totals(db, hid, pstart, pend, cur)
    cur_net, prev_net = Decimal(this["net_spending"]), Decimal(prev["net_spending"])
    mom = None if prev_net == 0 else round(float((cur_net - prev_net) / prev_net * 100), 1)
    budgets = budget_status(db, hid, cur, today=min(date.today(), end - timedelta(days=1)) if start <= date.today() else start)
    overall = next((b for b in budgets if b["category_id"] is None and b["period"] == "monthly"), None)
    upcoming = db.scalars(
        select(RecurringExpense)
        .where(RecurringExpense.household_id == hid, RecurringExpense.status == "active", RecurringExpense.next_due_date <= date.today() + timedelta(days=14))
        .order_by(RecurringExpense.next_due_date)
        .limit(10)
    ).all()
    pending_docs = db.scalar(select(func.count()).select_from(Document).where(Document.household_id == hid, Document.status == "needs_review"))
    failed_docs = db.scalar(select(func.count()).select_from(Document).where(Document.household_id == hid, Document.status == "failed"))
    dup_alerts = db.scalar(
        select(func.count()).select_from(ReconciliationMatch).where(
            ReconciliationMatch.household_id == hid, ReconciliationMatch.status == "suggested", ReconciliationMatch.confidence.in_(("high", "medium"))
        )
    )
    from app.models import SourceRecord

    counts = dict(
        db.execute(select(SourceRecord.reconciliation_status, func.count()).where(SourceRecord.household_id == hid, SourceRecord.status == "active").group_by(SourceRecord.reconciliation_status)).all()
    )
    eligible = sum(counts.values())
    done = sum(counts.get(k, 0) for k in ("matched", "fully_paid", "reversed"))
    from app.models import Account
    from app.modules.cards.service import card_summary

    card_accounts = db.scalars(
        select(Account).where(Account.household_id == hid, Account.type == "credit_card", Account.is_archived.is_(False), Account.currency == cur)
    ).all()
    cards = [card_summary(ctx, a) for a in card_accounts]
    due_bills = [c for c in cards if c["last_statement"] and c["last_statement"]["status"] not in ("paid", "no_dues")]
    next_bill = min(due_bills, key=lambda c: c["last_statement"]["due_date"], default=None)
    loans = loan_balances(db, hid, cur)
    shared = shared_balances(db, hid, cur)
    return {
        "owed_to_you": format(Decimal(loans["receivable"]) + Decimal(shared["receivable"]), "f"),
        "you_owe": format(Decimal(loans["payable"]) + Decimal(shared["payable"]), "f"),
        "month": f"{start.year:04d}-{start.month:02d}",
        "currency": cur,
        "totals": this,
        "previous_month_totals": prev,
        "month_over_month_net_spending_pct": mom,
        "remaining_budget": overall["remaining"] if overall else None,
        "overall_budget": overall,
        "budgets": budgets,
        "credit_cards": {
            "count": len(cards),
            "total_outstanding": format(sum((Decimal(c["outstanding"]) for c in cards), ZERO), "f"),
            "next_bill": (
                {
                    "account_id": next_bill["account_id"],
                    "name": next_bill["name"],
                    "due_date": next_bill["last_statement"]["due_date"],
                    "remaining_amount": next_bill["last_statement"]["remaining_amount"],
                    "minimum_remaining": next_bill["last_statement"]["minimum_remaining"],
                    "status": next_bill["last_statement"]["status"],
                }
                if next_bill
                else None
            ),
        },
        "outstanding_loans": loans,
        "unsettled_shared_expenses": shared,
        "upcoming_recurring": [
            {"id": str(r.id), "name": r.name, "amount": format(Decimal(r.amount), "f"), "currency": r.currency, "next_due_date": r.next_due_date.isoformat(), "is_subscription": r.is_subscription, "predicted": True}
            for r in upcoming
        ],
        "pending_document_reviews": pending_docs,
        "failed_documents": failed_docs,
        "duplicate_alerts": dup_alerts,
        "reconciliation_completion_rate": round(done / eligible, 4) if eligible else 1.0,
        "other_currencies": other_currency_spending(db, hid, start, end, cur),
    }


# ------------------------------------------------------------------ charts
def _expense_rows(db: Session, hid, start, end, currency):
    return db.scalars(
        select(CT)
        .options(selectinload(CT.line_items))
        .where(CT.household_id == hid, CT.status == "active", CT.currency == currency, CT.type.in_(("expense", "refund")), CT.occurred_on >= start, CT.occurred_on < end)
    ).all()


def category_breakdown(db: Session, hid, start, end, currency, level: str = "top") -> list[dict]:
    """Net spending by category. When a receipt's line items carry categories and add up to the bill,
    the counted amount is split across those item categories."""
    idx = CategoryIndex(db, hid)
    totals: dict = defaultdict(lambda: ZERO)
    for t in _expense_rows(db, hid, start, end, currency):
        sign = Decimal(1) if t.type == "expense" else Decimal(-1)
        eff = Decimal(t.effective_amount) * sign
        items = [li for li in t.line_items if li.line_total is not None and li.category_id]
        items_total = sum((Decimal(li.line_total) for li in items), ZERO)
        parts = []
        if items and items_total > 0 and len(items) == len(t.line_items):
            for li in items:
                parts.append((li.category_id, eff * Decimal(li.line_total) / items_total))
        else:
            parts.append((t.category_id, eff))
        for cid, amt in parts:
            key = idx.top_level(cid) if level == "top" else cid
            totals[key] += amt
    out = []
    for cid, amt in totals.items():
        amt = quantize(amt, currency)
        if amt == 0:
            continue
        c = idx.by_id.get(cid)
        out.append({"category_id": str(cid) if cid else None, "name": c.name if c else "Uncategorized", "color": c.color if c else "#94a3b8", "amount": format(amt, "f")})
    return sorted(out, key=lambda r: Decimal(r["amount"]), reverse=True)


def monthly_trend(db: Session, hid, currency, months: int = 12, end_month: str | None = None) -> list[dict]:
    start, _ = month_bounds(end_month)
    out = []
    cursor = start
    series = []
    for _ in range(months):
        series.append(cursor)
        cursor = month_bounds(prev_month(cursor))[0]
    for s in reversed(series):
        e = month_bounds(f"{s.year:04d}-{s.month:02d}")[1]
        t = period_totals(db, hid, s, e, currency)
        out.append({"month": f"{s.year:04d}-{s.month:02d}", "gross_spending": t["gross_spending"], "refunds": t["refunds"], "net_spending": t["net_spending"], "income": t["income"], "net_cash_flow": t["net_cash_flow"]})
    return out


def daily_spending(db: Session, hid, start, end, currency) -> list[dict]:
    rows = db.execute(
        select(CT.occurred_on, CT.type, func.sum(CT.effective_amount))
        .where(CT.household_id == hid, CT.status == "active", CT.currency == currency, CT.type.in_(("expense", "refund")), CT.occurred_on >= start, CT.occurred_on < end)
        .group_by(CT.occurred_on, CT.type)
    ).all()
    by_day: dict = defaultdict(lambda: ZERO)
    for d, typ, v in rows:
        by_day[d] += Decimal(v) if typ == "expense" else -Decimal(v)
    out = []
    d = start
    while d < end:
        out.append({"date": d.isoformat(), "net_spending": format(quantize(by_day.get(d, ZERO), currency), "f")})
        d += timedelta(days=1)
    return out


def top_merchants(db: Session, hid, start, end, currency, limit: int = 10) -> dict:
    m = db.execute(
        select(Merchant.id, Merchant.name, func.sum(CT.effective_amount), func.count())
        .join(CT, CT.merchant_id == Merchant.id)
        .where(CT.household_id == hid, CT.status == "active", CT.type == "expense", CT.currency == currency, CT.occurred_on >= start, CT.occurred_on < end, CT.effective_amount > 0)
        .group_by(Merchant.id, Merchant.name)
        .order_by(func.sum(CT.effective_amount).desc())
        .limit(limit)
    ).all()
    p = db.execute(
        select(Counterparty.id, Counterparty.name, func.sum(CT.cash_amount), func.count())
        .join(CT, CT.counterparty_id == Counterparty.id)
        .where(CT.household_id == hid, CT.status == "active", CT.currency == currency, CT.occurred_on >= start, CT.occurred_on < end)
        .group_by(Counterparty.id, Counterparty.name)
        .order_by(func.sum(CT.cash_amount).desc())
        .limit(limit)
    ).all()
    return {
        "merchants": [{"id": str(i), "name": n, "amount": format(quantize(v, currency), "f"), "count": c} for i, n, v, c in m],
        "counterparties": [{"id": str(i), "name": n, "amount": format(quantize(v, currency), "f"), "count": c} for i, n, v, c in p],
    }


def payment_methods(db: Session, hid, start, end, currency) -> list[dict]:
    rows = db.execute(
        select(CT.payment_method, func.sum(CT.effective_amount))
        .where(CT.household_id == hid, CT.status == "active", CT.type == "expense", CT.currency == currency, CT.occurred_on >= start, CT.occurred_on < end)
        .group_by(CT.payment_method)
    ).all()
    return sorted(
        [{"payment_method": pm or "unspecified", "amount": format(quantize(v, currency), "f")} for pm, v in rows if Decimal(v) > 0], key=lambda r: Decimal(r["amount"]), reverse=True
    )


def fixed_vs_variable(db: Session, hid, start, end, currency) -> dict:
    idx = CategoryIndex(db, hid)
    fixed = variable = ZERO
    for t in _expense_rows(db, hid, start, end, currency):
        amt = Decimal(t.effective_amount) * (1 if t.type == "expense" else -1)
        c = idx.by_id.get(t.category_id)
        top = idx.by_id.get(idx.top_level(t.category_id)) if t.category_id else None
        if t.is_recurring or (c and c.is_fixed) or (top and top.is_fixed):
            fixed += amt
        else:
            variable += amt
    return {"fixed": format(quantize(fixed, currency), "f"), "variable": format(quantize(variable, currency), "f"), "currency": currency}

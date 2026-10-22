"""Notifications are deduplicated by (household, dedupe_key) so periodic checks never spam."""
import statistics
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.money import fmt
from app.models import CanonicalTransaction, Household, ReconciliationMatch, RecurringExpense, SourceRecord
from app.models.planning import Notification


def notify(db: Session, household_id, kind: str, title: str, body: str = "", link: str = "", *, key: str, severity: str = "info", user_id=None) -> bool:
    stmt = (
        insert(Notification)
        .values(id=uuid.uuid4(), household_id=household_id, user_id=user_id, kind=kind, severity=severity, title=title[:200], body=body, link=link[:300], dedupe_key=key[:200])
        .on_conflict_do_nothing(index_elements=["household_id", "dedupe_key"])
        .returning(Notification.id)
    )
    created = db.execute(stmt).scalar() is not None
    db.commit()
    return created


def run_checks(db: Session, household: Household, today: date | None = None) -> int:
    """Budget thresholds, upcoming bills, duplicate-payment warnings, unmatched receipts, unusual spending."""
    from app.modules.analytics.service import budget_status

    today = today or date.today()
    hid = household.id
    created = 0
    cur = household.base_currency

    for b in budget_status(db, hid, cur, today):
        if b["state"] in ("warning", "over"):
            sev = "critical" if b["state"] == "over" else "warning"
            status_text = "over budget" if b["state"] == "over" else f"{b['percent_used']}% used"
            title = f"{b['name']}: {status_text}"
            created += notify(db, hid, "budget_threshold", title, f"Spent {fmt(b['spent'], cur)} of {fmt(b['amount'], cur)} this {b['period'][:-2]}.", "/budgets", key=f"budget:{b['budget_id']}:{b['period_start']}:{b['state']}", severity=sev)

    for r in db.scalars(select(RecurringExpense).where(RecurringExpense.household_id == hid, RecurringExpense.status == "active")).all():
        days = (r.next_due_date - today).days
        if 0 <= days <= r.remind_days_before:
            created += notify(db, hid, "upcoming_bill", f"{r.name} due {'today' if days == 0 else f'in {days} day(s)'}", f"Expected {fmt(r.amount, r.currency)} on {r.next_due_date.isoformat()} (prediction).", "/recurring", key=f"recurring:{r.id}:{r.next_due_date}")
        elif days < 0:
            created += notify(db, hid, "overdue_bill", f"{r.name} looks overdue", f"It was expected on {r.next_due_date.isoformat()}. Mark it paid or update the schedule.", "/recurring", key=f"recurring-overdue:{r.id}:{r.next_due_date}", severity="warning")

    created += _card_checks(db, household, today)

    high = db.scalars(
        select(ReconciliationMatch).where(ReconciliationMatch.household_id == hid, ReconciliationMatch.status == "suggested", ReconciliationMatch.confidence == "high", ReconciliationMatch.kind == "duplicate")
    ).all()
    for m in high:
        created += notify(db, hid, "duplicate_payment", "Possible duplicate payment", "Two records look like the same payment. Review them so it isn't counted twice.", "/reconciliation", key=f"dup:{m.id}", severity="warning")

    stale = db.scalars(
        select(SourceRecord).where(
            SourceRecord.household_id == hid,
            SourceRecord.role == "bill",
            SourceRecord.status == "active",
            SourceRecord.reconciliation_status == "unmatched",
            SourceRecord.source_type.in_(("receipt", "invoice")),
            SourceRecord.occurred_on <= today - timedelta(days=7),
            SourceRecord.occurred_on >= today - timedelta(days=60),
        )
    ).all()
    if stale:
        created += notify(db, hid, "unmatched_receipts", f"{len(stale)} receipt(s) without a matching payment", "If you paid by UPI or card, import the statement or link the payment so totals stay accurate.", "/reconciliation", key=f"unmatched-receipts:{today.isocalendar()[0]}-{today.isocalendar()[1]}")

    recent = db.scalars(
        select(CanonicalTransaction).where(
            CanonicalTransaction.household_id == hid, CanonicalTransaction.status == "active", CanonicalTransaction.type == "expense", CanonicalTransaction.occurred_on >= today - timedelta(days=3)
        )
    ).all()
    for t in recent:
        if not t.category_id:
            continue
        history = db.scalars(
            select(CanonicalTransaction.effective_amount).where(
                CanonicalTransaction.household_id == hid,
                CanonicalTransaction.category_id == t.category_id,
                CanonicalTransaction.status == "active",
                CanonicalTransaction.type == "expense",
                CanonicalTransaction.occurred_on >= today - timedelta(days=180),
                CanonicalTransaction.id != t.id,
            )
        ).all()
        if len(history) >= 5:
            med = Decimal(str(statistics.median([Decimal(h) for h in history])))
            if med > 0 and Decimal(t.effective_amount) > med * 3 and Decimal(t.effective_amount) - med > Decimal("500"):
                created += notify(db, hid, "unusual_spending", f"Unusually large expense: {t.description or 'transaction'}", f"{fmt(t.effective_amount, t.currency)} is more than 3× your typical {fmt(med, t.currency)} in this category.", f"/transactions?open={t.id}", key=f"unusual:{t.id}", severity="warning")
    return created


def _card_checks(db: Session, household: Household, today: date) -> int:
    """Credit card bills: due soon, overdue, and high utilisation."""
    from types import SimpleNamespace

    from app.models import Account, CreditCardStatement
    from app.modules.cards.service import card_summary, statement_state

    created = 0
    hid = household.id
    ctx = SimpleNamespace(db=db, household_id=hid)
    statements = db.scalars(
        select(CreditCardStatement).where(CreditCardStatement.household_id == hid, CreditCardStatement.due_date >= today - timedelta(days=60))
    ).all()
    for s in statements:
        st = statement_state(ctx, s, today)
        if st["status"] in ("paid", "no_dues"):
            continue
        card = db.get(Account, s.account_id)
        rem, mn = fmt(st["remaining_amount"], s.currency), fmt(st["minimum_remaining"], s.currency)
        if st["status"] == "overdue":
            created += notify(
                db, hid, "card_bill_overdue", f"{card.name} bill is overdue",
                f"{rem} remaining (minimum {mn}) was due on {s.due_date.isoformat()}. Late fees and interest may apply.",
                "/credit-cards", key=f"card-overdue:{s.id}", severity="critical",
            )
        elif 0 <= st["days_until_due"] <= 5:
            when = "today" if st["days_until_due"] == 0 else f"in {st['days_until_due']} day(s)"
            created += notify(
                db, hid, "card_bill_due", f"{card.name} bill due {when}",
                f"{rem} remaining; minimum due {mn}. Pay in full to avoid interest.",
                "/credit-cards", key=f"card-due:{s.id}:{st['days_until_due'] <= 1}", severity="warning",
            )
    cards = db.scalars(
        select(Account).where(Account.household_id == hid, Account.type == "credit_card", Account.is_archived.is_(False), Account.credit_limit.is_not(None))
    ).all()
    for card in cards:
        summary = card_summary(ctx, card, today)
        if summary["utilization_pct"] is not None and summary["utilization_pct"] >= 80:
            created += notify(
                db, hid, "card_high_utilization", f"{card.name} is {summary['utilization_pct']}% utilised",
                f"Outstanding {fmt(summary['outstanding'], card.currency)} of a {fmt(summary['credit_limit'], card.currency)} limit.",
                "/credit-cards", key=f"card-util:{card.id}:{today.strftime('%Y-%m')}", severity="warning",
            )
    return created

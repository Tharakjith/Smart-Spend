import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import MONEY, Base, IdMixin, TimestampMixin, utcnow


class Loan(IdMixin, TimestampMixin, Base):
    __tablename__ = "loans"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("counterparties.id"), index=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # given | received
    principal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    interest_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="open", nullable=False)  # open | settled | written_off
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))

    repayments: Mapped[list["LoanRepayment"]] = relationship(cascade="all, delete-orphan", order_by="LoanRepayment.paid_on")

    __table_args__ = (
        CheckConstraint("principal > 0", name="principal_positive"),
        CheckConstraint("direction in ('given','received')", name="direction_valid"),
    )


class LoanRepayment(IdMixin, Base):
    __tablename__ = "loan_repayments"
    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True, nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    interest_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))
    interest_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("principal_amount >= 0 and interest_amount >= 0", name="amounts_nonneg"),
        CheckConstraint("principal_amount + interest_amount > 0", name="amount_positive"),
    )


class SharedExpense(IdMixin, TimestampMixin, Base):
    __tablename__ = "shared_expenses"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="CASCADE"), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Who paid the merchant: the household ("self") or a counterparty.
    payer_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("counterparties.id"))
    split_method: Mapped[str] = mapped_column(String(10), default="equal", nullable=False)  # equal | exact | percent
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    participants: Mapped[list["SharedExpenseParticipant"]] = relationship(cascade="all, delete-orphan", back_populates="shared_expense")


class SharedExpenseParticipant(IdMixin, Base):
    __tablename__ = "shared_expense_participants"
    shared_expense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shared_expenses.id", ondelete="CASCADE"), index=True, nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("counterparties.id"))  # null = self
    share_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    settled_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    due_date: Mapped[date | None] = mapped_column(Date)

    shared_expense: Mapped[SharedExpense] = relationship(back_populates="participants")

    __table_args__ = (
        UniqueConstraint("shared_expense_id", "counterparty_id", postgresql_nulls_not_distinct=True),
        CheckConstraint("share_amount >= 0", name="share_nonneg"),
        CheckConstraint("settled_amount >= 0 and settled_amount <= share_amount", name="settled_bounds"),
    )


class SharedExpenseSettlement(IdMixin, Base):
    __tablename__ = "shared_expense_settlements"
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shared_expense_participants.id", ondelete="CASCADE"), index=True, nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    settled_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)


class Budget(IdMixin, TimestampMixin, Base):
    __tablename__ = "budgets"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # monthly | weekly
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("period in ('monthly','weekly')", name="period_valid"),
        CheckConstraint("alert_threshold_pct between 1 and 100", name="threshold_valid"),
    )


class SavingsGoal(IdMixin, TimestampMixin, Base):
    __tablename__ = "savings_goals"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    saved_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="active", nullable=False)

    __table_args__ = (CheckConstraint("target_amount > 0 and saved_amount >= 0", name="amounts_valid"),)


class RecurringExpense(IdMixin, TimestampMixin, Base):
    __tablename__ = "recurring_expenses"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("counterparties.id", ondelete="SET NULL"))
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)  # weekly | monthly | quarterly | yearly
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_subscription: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)  # active | paused | suggested | cancelled
    detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remind_days_before: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("frequency in ('weekly','monthly','quarterly','yearly')", name="frequency_valid"),
    )


class Notification(IdMixin, Base):
    __tablename__ = "notifications"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="info", nullable=False)  # info | warning | critical
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    __table_args__ = (UniqueConstraint("household_id", "dedupe_key"),)

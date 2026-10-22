import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import MONEY, Base, IdMixin, TimestampMixin, utcnow
from app.models.identity import JSONType


class CreditCardStatement(IdMixin, TimestampMixin, Base):
    """A credit card bill: what the bank says is owed for one billing cycle, and by when.

    Paying it never counts as spending (the card purchases already did); payments are linked through
    CreditCardBillPayment so the bill's paid/remaining/overdue state is always derived, never typed in.
    """

    __tablename__ = "credit_card_statements"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)  # cycle end / bill generation date
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_due: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    minimum_due: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    interest_charged: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    fees_charged: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    # Expense transactions created for interest/fees when the user chose to record them.
    charge_transaction_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        UniqueConstraint("account_id", "statement_date"),
        CheckConstraint("total_due >= 0 and minimum_due >= 0 and minimum_due <= total_due", name="amounts_valid"),
        CheckConstraint("interest_charged >= 0 and fees_charged >= 0", name="charges_nonneg"),
        CheckConstraint("period_start <= statement_date and statement_date <= due_date", name="dates_ordered"),
    )


class CreditCardBillPayment(IdMixin, Base):
    """Links a card payment (a credit_card_payment transaction) to the bill it settles, fully or partly."""

    __tablename__ = "credit_card_bill_payments"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    statement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("credit_card_statements.id", ondelete="CASCADE"), index=True, nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="CASCADE"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("statement_id", "transaction_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

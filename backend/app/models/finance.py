import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import MONEY, Base, IdMixin, TimestampMixin
from app.models.identity import JSONType

ACCOUNT_TYPES = ("cash", "bank", "upi", "debit_card", "credit_card", "wallet", "other")
PAYMENT_METHODS = ("cash", "upi", "debit_card", "credit_card", "bank_transfer", "net_banking", "wallet", "cheque", "other")

# Transaction type -> cash direction. "internal" never counts as spending or income.
TRANSACTION_TYPES = {
    "expense": "out",
    "income": "in",
    "transfer": "internal",
    "refund": "in",
    "loan_given": "out",
    "loan_received": "in",
    "loan_repayment_paid": "out",
    "loan_repayment_received": "in",
    "reimbursement_paid": "out",
    "reimbursement_received": "in",
    "credit_card_payment": "internal",
}
TX_STATUSES = ("active", "voided", "merged", "reversed")
RECON_STATUSES = (
    "unmatched",
    "suggested_match",
    "matched",
    "partially_paid",
    "fully_paid",
    "partially_reconciled",
    "needs_review",
    "disputed",
    "reversed",
)


def _in(col: str, values) -> str:
    return f"{col} in (" + ",".join(f"'{v}'" for v in values) + ")"


class Account(IdMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    opening_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    opening_balance_date: Mapped[date | None] = mapped_column(Date)
    institution: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    masked_number: Mapped[str] = mapped_column(String(8), default="", nullable=False)  # last 4 digits only
    upi_handle: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Credit cards only.
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY)
    statement_day: Mapped[int | None] = mapped_column(Integer)  # day of month the statement is generated
    due_day: Mapped[int | None] = mapped_column(Integer)  # day of month payment is due

    __table_args__ = (
        UniqueConstraint("household_id", "name"),
        CheckConstraint(_in("type", ACCOUNT_TYPES), name="type_valid"),
        CheckConstraint("credit_limit is null or credit_limit >= 0", name="credit_limit_nonneg"),
        CheckConstraint("statement_day is null or statement_day between 1 and 31", name="statement_day_valid"),
        CheckConstraint("due_day is null or due_day between 1 and 31", name="due_day_valid"),
    )


class Category(IdMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="expense")  # expense | income | other
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        # NULLS NOT DISTINCT so two top-level categories with the same name are rejected too.
        Index("uq_categories_sibling_name", "household_id", "parent_id", "name", unique=True, postgresql_nulls_not_distinct=True),
    )


class Merchant(IdMixin, TimestampMixin, Base):
    __tablename__ = "merchants"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    upi_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    aliases: Mapped[list["MerchantAlias"]] = relationship(cascade="all, delete-orphan", back_populates="merchant")

    __table_args__ = (UniqueConstraint("household_id", "normalized_name"),)


class MerchantAlias(IdMixin, Base):
    __tablename__ = "merchant_aliases"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # user | confirmed_match | system
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    merchant: Mapped[Merchant] = relationship(back_populates="aliases")

    __table_args__ = (UniqueConstraint("household_id", "normalized_alias"),)


class Counterparty(IdMixin, TimestampMixin, Base):
    __tablename__ = "counterparties"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    upi_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (UniqueConstraint("household_id", "name"),)


class UserRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_rules"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    field: Mapped[str] = mapped_column(String(20), nullable=False)  # description | merchant | item | counterparty
    operator: Mapped[str] = mapped_column(String(20), nullable=False)  # contains | equals | starts_with | regex
    pattern: Mapped[str] = mapped_column(String(300), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    set_type: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("field", ("description", "merchant", "item", "counterparty")), name="field_valid"),
        CheckConstraint(_in("operator", ("contains", "equals", "starts_with", "regex")), name="operator_valid"),
        CheckConstraint("category_id is not null or set_type is not null", name="has_effect"),
    )


class CanonicalTransaction(IdMixin, TimestampMixin, Base):
    """The ledger. One row per real-world financial event. All totals come from here."""

    __tablename__ = "canonical_transactions"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Amount that counts toward totals: amount minus portions absorbed by bills via allocations.
    effective_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Money that actually moved for this record (balances, cash flow). A bill with linked payments has
    # cash_amount 0 because the payments carry the cash; an unlinked bill is assumed paid directly.
    cash_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    category_source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    # Why an automatic category was chosen, e.g. ["bill text: 'water charge'", "merchant: 'kwa'"].
    category_reasons: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"), index=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("counterparties.id", ondelete="SET NULL"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), index=True)
    to_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    payment_method: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))
    related_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))
    reconciliation_status: Mapped[str] = mapped_column(String(24), default="unmatched", nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), default="confirmed", nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    line_items: Mapped[list["TransactionLineItem"]] = relationship(
        cascade="all, delete-orphan", order_by="TransactionLineItem.position", back_populates="transaction"
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonneg"),
        CheckConstraint("effective_amount >= 0 and effective_amount <= amount", name="effective_bounds"),
        CheckConstraint("cash_amount >= 0 and cash_amount <= amount", name="cash_bounds"),
        CheckConstraint(_in("type", TRANSACTION_TYPES), name="type_valid"),
        CheckConstraint(_in("status", TX_STATUSES), name="status_valid"),
        CheckConstraint(_in("reconciliation_status", RECON_STATUSES), name="recon_valid"),
        CheckConstraint("status <> 'merged' or merged_into_id is not null", name="merged_has_target"),
        Index("ix_ctx_household_date", "household_id", "occurred_on"),
        Index("ix_ctx_household_type_status", "household_id", "type", "status"),
    )


class TransactionLineItem(IdMixin, Base):
    __tablename__ = "transaction_line_items"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="CASCADE"), index=True, nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    brand: Mapped[str | None] = mapped_column(String(120))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    discount: Mapped[Decimal | None] = mapped_column(MONEY)
    tax: Mapped[Decimal | None] = mapped_column(MONEY)
    line_total: Mapped[Decimal | None] = mapped_column(MONEY)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    # Normalised for price comparisons: dimension (mass|volume|count) and quantity in base unit (kg, l, unit).
    unit_dimension: Mapped[str | None] = mapped_column(String(10))
    base_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))

    transaction: Mapped[CanonicalTransaction] = relationship(back_populates="line_items")

    __table_args__ = (Index("ix_line_items_household_name", "household_id", "normalized_name"),)


class SourceRecord(IdMixin, TimestampMixin, Base):
    """One piece of evidence (receipt, statement row, screenshot, manual entry) exactly as received."""

    __tablename__ = "source_records"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    canonical_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_transactions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The canonical transaction this record was created with; restored on unmerge.
    original_transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # manual | receipt | invoice | statement_row | upi_screenshot
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # bill | payment
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # out | in | internal
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merchant_raw: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    merchant_normalized: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(20))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    upi_txn_id: Mapped[str | None] = mapped_column(String(64), index=True)
    utr: Mapped[str | None] = mapped_column(String(64), index=True)
    bank_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(64), index=True)
    order_id: Mapped[str | None] = mapped_column(String(64))
    item_names: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    statement_row_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("statement_rows.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default="active", nullable=False)  # active | reversed | voided
    reconciliation_status: Mapped[str] = mapped_column(String(24), default="unmatched", nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)

    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonneg"),
        CheckConstraint("allocated_amount >= 0 and allocated_amount <= amount", name="allocated_bounds"),
        CheckConstraint("role in ('bill','payment')", name="role_valid"),
        CheckConstraint(_in("reconciliation_status", RECON_STATUSES), name="recon_valid"),
        Index("uq_source_document", "document_id", unique=True, postgresql_where=text("document_id is not null")),
        Index("uq_source_statement_row", "statement_row_id", unique=True, postgresql_where=text("statement_row_id is not null")),
        Index("ix_source_household_date", "household_id", "occurred_on"),
    )

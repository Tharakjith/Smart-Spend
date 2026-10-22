import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import MONEY, Base, IdMixin, TimestampMixin, utcnow
from app.models.identity import JSONType

MATCH_KINDS = ("bill_payment", "duplicate", "refund")
MATCH_STATUSES = ("suggested", "confirmed", "rejected", "unlinked")


class ReconciliationMatch(IdMixin, TimestampMixin, Base):
    """A suggested or confirmed relationship between two source records.

    bill_payment: a = bill, b = payment.  duplicate: a = primary, b = secondary.  refund: a = original, b = refund.
    """

    __tablename__ = "reconciliation_matches"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    a_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_records.id", ondelete="CASCADE"), index=True, nullable=False)
    b_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_records.id", ondelete="CASCADE"), index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)  # high | medium | low
    reasons: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    conflict: Mapped[bool] = mapped_column(default=False, nullable=False)
    amount_difference: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    date_difference_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    merchant_similarity: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("0"))
    suggested_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(12), default="suggested", nullable=False)
    origin: Mapped[str] = mapped_column(String(8), default="engine", nullable=False)  # engine | manual
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        CheckConstraint("a_source_id <> b_source_id", name="distinct_sources"),
        CheckConstraint("kind in ('bill_payment','duplicate','refund')", name="kind_valid"),
        CheckConstraint("status in ('suggested','confirmed','rejected','unlinked')", name="status_valid"),
        # One row per unordered pair and kind, whatever order the engine saw them in.
        Index(
            "uq_recon_match_pair",
            "household_id",
            func.least(a_source_id, b_source_id),
            func.greatest(a_source_id, b_source_id),
            "kind",
            unique=True,
        ),
    )


class ReconciliationAllocation(IdMixin, Base):
    """'amount' of payment source settles bill source. Many-to-many."""

    __tablename__ = "reconciliation_allocations"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reconciliation_matches.id", ondelete="SET NULL"))
    payment_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_records.id", ondelete="CASCADE"), index=True, nullable=False)
    bill_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_records.id", ondelete="CASCADE"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)  # active | removed
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    removed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("payment_source_id <> bill_source_id", name="distinct_sources"),
        Index(
            "uq_active_allocation",
            "payment_source_id",
            "bill_source_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class ReconciliationAuditLog(IdMixin, Base):
    __tablename__ = "reconciliation_audit_logs"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reconciliation_matches.id", ondelete="SET NULL"), index=True)
    allocation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reconciliation_allocations.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DuplicateCandidate(IdMixin, Base):
    """Exact duplicates caught before they became records: re-uploaded files and re-imported statement rows."""

    __tablename__ = "duplicate_candidates"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # document_hash | statement_row
    existing_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    existing_statement_row_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("statement_rows.id", ondelete="CASCADE"))
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("statement_imports.id", ondelete="CASCADE"))
    attempted_filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    details: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)  # open | dismissed
    detected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import MONEY, Base, IdMixin, TimestampMixin, utcnow
from app.models.identity import JSONType

DOCUMENT_STATUSES = ("uploaded", "queued", "processing", "needs_review", "confirmed", "failed", "archived")


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", nullable=False)
    doc_kind: Mapped[str] = mapped_column(String(20), default="receipt", nullable=False)  # receipt | invoice | upi_screenshot
    page_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        UniqueConstraint("household_id", "sha256"),
        CheckConstraint("status in (" + ",".join(f"'{s}'" for s in DOCUMENT_STATUSES) + ")", name="status_valid"),
    )


class DocumentProcessingJob(IdMixin, Base):
    __tablename__ = "document_processing_jobs"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, default="extract")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")  # queued | running | succeeded | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractedDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "extracted_documents"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf_text | ocr | manual
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # {field: {"value": ..., "confidence": 0..1}} - missing fields are null, never guessed.
    fields: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    line_items: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    validation: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    overall_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"), nullable=False)
    suggested_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    category_reasons: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    suggested_merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_transactions.id", ondelete="SET NULL"))


class StatementImport(IdMixin, TimestampMixin, Base):
    __tablename__ = "statement_imports"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    file_format: Mapped[str] = mapped_column(String(8), nullable=False)  # csv | xlsx | pdf
    source_kind: Mapped[str] = mapped_column(String(20), default="bank", nullable=False)  # bank | credit_card | upi | wallet
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    date_format: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="uploaded", nullable=False)  # uploaded | mapped | confirmed | failed
    headers: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    raw_rows: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    column_mapping: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StatementRow(IdMixin, Base):
    __tablename__ = "statement_rows"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("statement_imports.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONType, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)  # out | in
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(64))
    balance: Mapped[Decimal | None] = mapped_column(MONEY)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("household_id", "fingerprint"), CheckConstraint("amount >= 0", name="amount_nonneg"))

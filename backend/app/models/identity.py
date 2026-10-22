import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, TimestampMixin, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")

ROLES = ("owner", "admin", "member", "viewer")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list["HouseholdMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class UserSession(IdMixin, Base):
    __tablename__ = "user_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class EmailToken(IdMixin, Base):
    __tablename__ = "email_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # verify_email | reset_password | mfa_login
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Household(IdMixin, TimestampMixin, Base):
    __tablename__ = "households"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    ai_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matching_config: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    members: Mapped[list["HouseholdMember"]] = relationship(back_populates="household", cascade="all, delete-orphan")


class HouseholdMember(IdMixin, Base):
    __tablename__ = "household_members"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    household: Mapped[Household] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("household_id", "user_id"),
        CheckConstraint("role in ('owner','admin','member','viewer')", name="role_valid"),
    )


class IdempotencyKey(IdMixin, Base):
    __tablename__ = "idempotency_keys"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(400), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("household_id", "key"),)


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    household_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import Ctx
from app.core.money import to_decimal
from app.models import AuditLog

T = TypeVar("T")


def _parse_money(v):
    if v is None:
        return v
    return to_decimal(v) if not isinstance(v, float) else to_decimal(repr(v))


# Accepts strings/ints/Decimals (and JSON numbers via their textual repr); serialises as a string so
# clients never round-trip money through binary floats.
Money = Annotated[Decimal, BeforeValidator(_parse_money), PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json")]
OptMoney = Annotated[Decimal | None, BeforeValidator(_parse_money), PlainSerializer(lambda v: None if v is None else format(v, "f"), return_type=str | None, when_used="json")]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def paginate(db: Session, stmt, page: int, page_size: int):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return items, total, page, page_size


def snapshot(obj, fields: list[str] | None = None) -> dict[str, Any]:
    out = {}
    cols = fields or [c.key for c in obj.__table__.columns]
    for k in cols:
        v = getattr(obj, k, None)
        if isinstance(v, (uuid.UUID, Decimal)):
            v = str(v)
        elif isinstance(v, (date, datetime)):
            v = v.isoformat()
        out[k] = v
    return out


def audit(ctx: Ctx, action: str, entity_type: str, entity_id, before: dict | None = None, after: dict | None = None) -> None:
    ctx.db.add(
        AuditLog(
            household_id=ctx.household_id,
            actor_id=ctx.user.id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            before=before,
            after=after,
            ip=ctx.ip,
        )
    )

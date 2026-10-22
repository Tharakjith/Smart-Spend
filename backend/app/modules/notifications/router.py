import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update

from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx
from app.core.errors import NotFound
from app.models.planning import Notification
from app.modules.notifications.service import run_checks

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _mine(ctx: Ctx):
    return (Notification.household_id == ctx.household_id, or_(Notification.user_id.is_(None), Notification.user_id == ctx.user.id))


@router.get("")
def list_notifications(ctx: Ctx = Depends(get_ctx), unread: bool = False, page: int = 1, page_size: int = Query(50, le=200)):
    q = select(Notification).where(*_mine(ctx))
    if unread:
        q = q.where(Notification.read_at.is_(None))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [
            {"id": str(n.id), "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link, "read": n.read_at is not None, "created_at": n.created_at.isoformat()}
            for n in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    n = ctx.db.get(Notification, notification_id)
    if n is None or n.household_id != ctx.household_id:
        raise NotFound("Notification not found")
    n.read_at = n.read_at or utcnow()
    ctx.db.commit()
    return {"ok": True}


@router.post("/read-all")
def read_all(ctx: Ctx = Depends(get_ctx)):
    ctx.db.execute(update(Notification).where(*_mine(ctx), Notification.read_at.is_(None)).values(read_at=utcnow()))
    ctx.db.commit()
    return {"ok": True}


@router.post("/run-checks")
def run(ctx: Ctx = Depends(get_ctx)):
    return {"created": run_checks(ctx.db, ctx.household)}

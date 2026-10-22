import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.errors import Forbidden, Unauthorized
from app.models import Household, HouseholdMember, User, UserSession
from app.core.security import decode_access_token

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


@dataclass
class AuthUser:
    user: User
    session_id: uuid.UUID


@dataclass
class Ctx:
    """Authenticated request context scoped to one household."""

    db: Session
    user: User
    household: Household
    role: str
    session_id: uuid.UUID
    ip: str = ""

    @property
    def household_id(self) -> uuid.UUID:
        return self.household.id

    def require(self, min_role: str) -> None:
        if ROLE_RANK[self.role] < ROLE_RANK[min_role]:
            raise Forbidden(f"This action requires the '{min_role}' role or higher", code="insufficient_role")


def get_auth_user(request: Request, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    try:
        payload = decode_access_token(authorization.split(" ", 1)[1])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Access token expired", code="token_expired")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid access token")
    session = db.get(UserSession, uuid.UUID(payload["sid"]))
    if session is None or session.revoked_at is not None or session.expires_at < utcnow():
        raise Unauthorized("Session has been revoked", code="session_revoked")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise Unauthorized("User is inactive")
    return AuthUser(user=user, session_id=session.id)


def get_ctx(
    request: Request,
    auth: AuthUser = Depends(get_auth_user),
    db: Session = Depends(get_db),
    x_household_id: str | None = Header(default=None),
) -> Ctx:
    q = select(HouseholdMember).where(HouseholdMember.user_id == auth.user.id)
    if x_household_id:
        try:
            hid = uuid.UUID(x_household_id)
        except ValueError:
            raise Forbidden("Invalid workspace id")
        q = q.where(HouseholdMember.household_id == hid)
    else:
        q = q.order_by(HouseholdMember.created_at)
    member = db.scalars(q.limit(1)).first()
    if member is None:
        # Same response whether the household exists or not: no information leak.
        raise Forbidden("You do not have access to this workspace", code="household_forbidden")
    household = db.get(Household, member.household_id)
    ip = request.client.host if request.client else ""
    return Ctx(db=db, user=auth.user, household=household, role=member.role, session_id=auth.session_id, ip=ip)


def writer_ctx(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    ctx.require("member")
    return ctx


def admin_ctx(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    ctx.require("admin")
    return ctx

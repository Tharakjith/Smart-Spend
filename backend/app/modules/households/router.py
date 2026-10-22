import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import EmailStr, Field
from sqlalchemy import func, select

from app.core.db import get_db
from app.core.deps import AuthUser, Ctx, get_auth_user, get_ctx
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models import Household, HouseholdMember, User
from app.modules.common import Schema, audit, snapshot
from app.modules.households.service import create_household

router = APIRouter(prefix="/households", tags=["households"])


class HouseholdIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    base_currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    timezone: str = "Asia/Kolkata"


class HouseholdPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None
    ai_opt_in: bool | None = None
    matching_config: dict | None = None


class MemberIn(Schema):
    email: EmailStr
    role: str = Field(pattern="^(admin|member|viewer)$")


class MemberPatch(Schema):
    role: str = Field(pattern="^(owner|admin|member|viewer)$")


def _out(h: Household, role: str | None = None) -> dict:
    return {
        "id": str(h.id),
        "name": h.name,
        "base_currency": h.base_currency,
        "timezone": h.timezone,
        "ai_opt_in": h.ai_opt_in,
        "matching_config": h.matching_config,
        "is_demo": h.is_demo,
        "role": role,
    }


def _membership(db, household_id: uuid.UUID, user_id: uuid.UUID) -> HouseholdMember:
    m = db.scalars(select(HouseholdMember).where(HouseholdMember.household_id == household_id, HouseholdMember.user_id == user_id)).first()
    if m is None:
        raise Forbidden("You do not have access to this household", code="household_forbidden")
    return m


@router.get("")
def list_households(auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    rows = db.execute(
        select(Household, HouseholdMember.role).join(HouseholdMember).where(HouseholdMember.user_id == auth.user.id).order_by(HouseholdMember.created_at)
    ).all()
    return [_out(h, r) for h, r in rows]


@router.post("", status_code=201)
def create(body: HouseholdIn, auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise ValidationFailed("Unknown timezone")
    h = create_household(db, auth.user, body.name, body.base_currency, body.timezone)
    db.commit()
    return _out(h, "owner")


@router.get("/{household_id}")
def get_one(household_id: uuid.UUID, auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    m = _membership(db, household_id, auth.user.id)
    return _out(db.get(Household, household_id), m.role)


@router.patch("/{household_id}")
def update(household_id: uuid.UUID, body: HouseholdPatch, ctx: Ctx = Depends(get_ctx)):
    if ctx.household_id != household_id:
        _membership(ctx.db, household_id, ctx.user.id)
        raise Forbidden("Select this household (X-Household-ID) to modify it")
    ctx.require("admin")
    h = ctx.household
    before = snapshot(h, ["name", "timezone", "ai_opt_in", "matching_config"])
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:
            raise ValidationFailed("Unknown timezone")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
    audit(ctx, "update", "household", h.id, before, snapshot(h, ["name", "timezone", "ai_opt_in", "matching_config"]))
    ctx.db.commit()
    return _out(h, ctx.role)


@router.get("/{household_id}/members")
def members(household_id: uuid.UUID, auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    _membership(db, household_id, auth.user.id)
    rows = db.execute(select(HouseholdMember, User).join(User).where(HouseholdMember.household_id == household_id).order_by(HouseholdMember.created_at)).all()
    return [{"user_id": str(u.id), "email": u.email, "full_name": u.full_name, "role": m.role, "joined_at": m.created_at} for m, u in rows]


@router.post("/{household_id}/members", status_code=201)
def add_member(household_id: uuid.UUID, body: MemberIn, ctx: Ctx = Depends(get_ctx)):
    if ctx.household_id != household_id:
        raise Forbidden("Select this household (X-Household-ID) to modify it")
    ctx.require("admin")
    user = ctx.db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    if user is None:
        raise NotFound("No registered user with that email. Ask them to sign up first.", code="user_not_found")
    exists = ctx.db.scalars(select(HouseholdMember).where(HouseholdMember.household_id == household_id, HouseholdMember.user_id == user.id)).first()
    if exists:
        raise Conflict("User is already a member")
    ctx.db.add(HouseholdMember(household_id=household_id, user_id=user.id, role=body.role))
    audit(ctx, "add_member", "household", household_id, None, {"user_id": str(user.id), "role": body.role})
    ctx.db.commit()
    return {"ok": True}


@router.patch("/{household_id}/members/{user_id}")
def change_role(household_id: uuid.UUID, user_id: uuid.UUID, body: MemberPatch, ctx: Ctx = Depends(get_ctx)):
    if ctx.household_id != household_id:
        raise Forbidden("Select this household (X-Household-ID) to modify it")
    ctx.require("admin")
    m = _membership(ctx.db, household_id, user_id)
    if (body.role == "owner" or m.role == "owner") and ctx.role != "owner":
        raise Forbidden("Only an owner can grant or remove the owner role")
    if m.role == "owner" and body.role != "owner":
        _ensure_other_owner(ctx, household_id, user_id)
    before = {"role": m.role}
    m.role = body.role
    audit(ctx, "change_role", "household_member", user_id, before, {"role": body.role})
    ctx.db.commit()
    return {"ok": True}


@router.delete("/{household_id}/members/{user_id}")
def remove_member(household_id: uuid.UUID, user_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    if ctx.household_id != household_id:
        raise Forbidden("Select this household (X-Household-ID) to modify it")
    if user_id != ctx.user.id:
        ctx.require("admin")
    m = _membership(ctx.db, household_id, user_id)
    if m.role == "owner":
        if ctx.role != "owner":
            raise Forbidden("Only an owner can remove an owner")
        _ensure_other_owner(ctx, household_id, user_id)
    ctx.db.delete(m)
    audit(ctx, "remove_member", "household_member", user_id, {"role": m.role}, None)
    ctx.db.commit()
    return {"ok": True}


def _ensure_other_owner(ctx: Ctx, household_id, user_id) -> None:
    owners = ctx.db.scalar(
        select(func.count()).select_from(HouseholdMember).where(
            HouseholdMember.household_id == household_id, HouseholdMember.role == "owner", HouseholdMember.user_id != user_id
        )
    )
    if not owners:
        raise Conflict("A household must keep at least one owner", code="last_owner")

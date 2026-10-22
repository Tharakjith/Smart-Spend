import secrets
import uuid
from datetime import timedelta

import pyotp
from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from pydantic import EmailStr, Field
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.deps import AuthUser, get_auth_user
from app.core.email import send_email
from app.core.errors import AppError, Forbidden, Unauthorized, ValidationFailed
from app.core.ratelimit import auth_rate_limit
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    decrypt,
    encrypt,
    hash_password,
    new_opaque_token,
    token_hash,
    validate_password_strength,
    verify_password,
)
from app.models import AuditLog, EmailToken, Household, HouseholdMember, User, UserSession
from app.modules.common import Schema
from app.modules.households.service import create_household

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "ss_refresh"
CSRF_COOKIE = "ss_csrf"
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


class RegisterIn(Schema):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    household_name: str | None = Field(default=None, max_length=200)
    base_currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")


class LoginIn(Schema):
    email: EmailStr
    password: str = Field(max_length=200)


class MfaVerifyIn(Schema):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class TokenIn(Schema):
    token: str


class EmailIn(Schema):
    email: EmailStr


class ResetIn(Schema):
    token: str
    new_password: str = Field(min_length=10, max_length=200)


class CodeIn(Schema):
    code: str = Field(min_length=6, max_length=8)


class DisableMfaIn(Schema):
    password: str
    code: str


class UserOut(Schema):
    id: uuid.UUID
    email: str
    full_name: str
    email_verified: bool
    mfa_enabled: bool


def user_out(u: User) -> dict:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, email_verified=u.email_verified_at is not None, mfa_enabled=u.mfa_enabled).model_dump(mode="json")


def _issue_email_token(db, user: User, purpose: str, ttl: timedelta) -> str:
    raw = new_opaque_token()
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=token_hash(raw), expires_at=utcnow() + ttl))
    return raw


def _consume_email_token(db, raw: str, purpose: str) -> EmailToken:
    tok = db.scalars(select(EmailToken).where(EmailToken.token_hash == token_hash(raw), EmailToken.purpose == purpose).with_for_update()).first()
    if tok is None or tok.used_at is not None or tok.expires_at < utcnow():
        raise ValidationFailed("This link is invalid or has expired", code="token_invalid")
    tok.used_at = utcnow()
    return tok


def _send_verification(db, user: User) -> None:
    raw = _issue_email_token(db, user, "verify_email", timedelta(hours=48))
    url = f"{get_settings().frontend_url}/verify-email?token={raw}"
    send_email(user.email, "Verify your SmartSpend email", f"Hi {user.full_name},\n\nConfirm your email address: {url}\n\nThis link expires in 48 hours.")


def _start_session(db, user: User, request: Request, response: Response) -> dict:
    s = get_settings()
    refresh = new_opaque_token()
    sess = UserSession(
        user_id=user.id,
        refresh_token_hash=token_hash(refresh),
        expires_at=utcnow() + timedelta(days=s.refresh_token_days),
        user_agent=(request.headers.get("user-agent") or "")[:400],
        ip=request.client.host if request.client else "",
    )
    db.add(sess)
    db.flush()
    _set_cookies(response, refresh)
    db.add(AuditLog(actor_id=user.id, action="login", entity_type="user", entity_id=str(user.id), ip=sess.ip))
    db.commit()
    return {"access_token": create_access_token(user.id, sess.id), "token_type": "bearer", "user": user_out(user)}


def _set_cookies(response: Response, refresh: str) -> None:
    s = get_settings()
    max_age = s.refresh_token_days * 86400
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=max_age, httponly=True, secure=s.cookie_secure, samesite="strict", path=f"{s.api_prefix}/auth")
    # Double-submit CSRF token: readable by the SPA, echoed in X-CSRF-Token for cookie-authenticated calls.
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(24), max_age=max_age, httponly=False, secure=s.cookie_secure, samesite="strict", path="/")


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path=f"{s.api_prefix}/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _check_csrf(csrf_cookie: str | None, csrf_header: str | None) -> None:
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise Forbidden("CSRF token missing or invalid", code="csrf_failed")


@router.post("/register", status_code=201, dependencies=[Depends(auth_rate_limit)])
def register(body: RegisterIn, db=Depends(get_db)):
    problems = validate_password_strength(body.password)
    if problems:
        raise ValidationFailed("Password must contain " + ", ".join(problems), code="weak_password")
    email = body.email.lower()
    if db.scalar(select(func.count()).select_from(User).where(func.lower(User.email) == email)):
        # Generic message to avoid confirming which emails are registered.
        raise AppError("Unable to register with this email", code="registration_failed", status_code=409)
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name.strip())
    if not get_settings().require_email_verification:
        user.email_verified_at = utcnow()
    db.add(user)
    db.flush()
    create_household(db, user, body.household_name or f"{user.full_name.split()[0]}'s Household", body.base_currency)
    if user.email_verified_at is None:
        _send_verification(db, user)
    db.add(AuditLog(actor_id=user.id, action="register", entity_type="user", entity_id=str(user.id)))
    db.commit()
    return {"user": user_out(user), "verification_required": user.email_verified_at is None}


@router.post("/login", dependencies=[Depends(auth_rate_limit)])
def login(body: LoginIn, request: Request, response: Response, db=Depends(get_db)):
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    if user is None:
        verify_password(body.password, DUMMY_HASH)
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    if user.locked_until and user.locked_until > utcnow():
        raise Unauthorized("Account temporarily locked after repeated failed logins. Try again later.", code="account_locked")
    if not verify_password(body.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= LOCKOUT_THRESHOLD:
            user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
        db.commit()
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise Unauthorized("Account disabled", code="account_disabled")
    if get_settings().require_email_verification and user.email_verified_at is None:
        raise Forbidden("Please verify your email address before signing in.", code="email_not_verified")
    user.failed_login_count = 0
    user.locked_until = None
    if user.mfa_enabled:
        raw = _issue_email_token(db, user, "mfa_login", timedelta(minutes=5))
        db.commit()
        return {"mfa_required": True, "mfa_token": raw}
    return _start_session(db, user, request, response)


@router.post("/mfa/verify", dependencies=[Depends(auth_rate_limit)])
def mfa_verify(body: MfaVerifyIn, request: Request, response: Response, db=Depends(get_db)):
    tok = _consume_email_token(db, body.mfa_token, "mfa_login")
    user = db.get(User, tok.user_id)
    if not user or not user.mfa_enabled or not pyotp.TOTP(decrypt(user.mfa_secret_enc)).verify(body.code, valid_window=1):
        db.rollback()
        raise Unauthorized("Invalid verification code", code="mfa_invalid")
    return _start_session(db, user, request, response)


@router.post("/refresh")
def refresh(
    response: Response,
    db=Depends(get_db),
    ss_refresh: str | None = Cookie(default=None),
    ss_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None),
):
    if not ss_refresh:
        raise Unauthorized("No refresh session", code="no_session")
    _check_csrf(ss_csrf, x_csrf_token)
    sess = db.scalars(select(UserSession).where(UserSession.refresh_token_hash == token_hash(ss_refresh)).with_for_update()).first()
    if sess is None or sess.revoked_at is not None or sess.expires_at < utcnow():
        _clear_cookies(response)
        raise Unauthorized("Session expired", code="session_expired")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        raise Unauthorized("User inactive")
    new_refresh = new_opaque_token()  # rotate on every use
    sess.refresh_token_hash = token_hash(new_refresh)
    sess.last_used_at = utcnow()
    db.commit()
    _set_cookies(response, new_refresh)
    return {"access_token": create_access_token(user.id, sess.id), "token_type": "bearer", "user": user_out(user)}


@router.post("/logout")
def logout(
    response: Response,
    db=Depends(get_db),
    ss_refresh: str | None = Cookie(default=None),
    ss_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None),
):
    _check_csrf(ss_csrf, x_csrf_token)
    if ss_refresh:
        sess = db.scalars(select(UserSession).where(UserSession.refresh_token_hash == token_hash(ss_refresh))).first()
        if sess and sess.revoked_at is None:
            sess.revoked_at = utcnow()
            db.commit()
    _clear_cookies(response)
    return {"ok": True}


@router.post("/verify-email")
def verify_email(body: TokenIn, db=Depends(get_db)):
    tok = _consume_email_token(db, body.token, "verify_email")
    user = db.get(User, tok.user_id)
    user.email_verified_at = user.email_verified_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/resend-verification", dependencies=[Depends(auth_rate_limit)])
def resend_verification(body: EmailIn, db=Depends(get_db)):
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    if user and user.email_verified_at is None:
        _send_verification(db, user)
        db.commit()
    return {"ok": True}


@router.post("/forgot-password", dependencies=[Depends(auth_rate_limit)])
def forgot_password(body: EmailIn, db=Depends(get_db)):
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    if user and user.is_active:
        raw = _issue_email_token(db, user, "reset_password", timedelta(hours=1))
        url = f"{get_settings().frontend_url}/reset-password?token={raw}"
        send_email(user.email, "Reset your SmartSpend password", f"Reset your password: {url}\n\nThis link expires in 1 hour. If you did not request it, ignore this email.")
        db.commit()
    return {"ok": True}  # identical response whether or not the email exists


@router.post("/reset-password", dependencies=[Depends(auth_rate_limit)])
def reset_password(body: ResetIn, db=Depends(get_db)):
    problems = validate_password_strength(body.new_password)
    if problems:
        raise ValidationFailed("Password must contain " + ", ".join(problems), code="weak_password")
    tok = _consume_email_token(db, body.token, "reset_password")
    user = db.get(User, tok.user_id)
    user.password_hash = hash_password(body.new_password)
    user.failed_login_count = 0
    user.locked_until = None
    # A password reset signs out every session.
    for sess in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))):
        sess.revoked_at = utcnow()
    db.add(AuditLog(actor_id=user.id, action="password_reset", entity_type="user", entity_id=str(user.id)))
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def list_sessions(auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    rows = db.scalars(
        select(UserSession).where(UserSession.user_id == auth.user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow()).order_by(UserSession.last_used_at.desc())
    ).all()
    return [
        {"id": str(s.id), "created_at": s.created_at, "last_used_at": s.last_used_at, "user_agent": s.user_agent, "ip": s.ip, "current": s.id == auth.session_id}
        for s in rows
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: uuid.UUID, auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    sess = db.get(UserSession, session_id)
    if sess is None or sess.user_id != auth.user.id:
        raise AppError("Session not found", code="not_found", status_code=404)
    sess.revoked_at = sess.revoked_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/mfa/setup")
def mfa_setup(auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    if auth.user.mfa_enabled:
        raise AppError("MFA is already enabled", code="mfa_already_enabled", status_code=409)
    secret = pyotp.random_base32()
    auth.user.mfa_secret_enc = encrypt(secret)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=auth.user.email, issuer_name="SmartSpend")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    if not auth.user.mfa_secret_enc or not pyotp.TOTP(decrypt(auth.user.mfa_secret_enc)).verify(body.code, valid_window=1):
        raise ValidationFailed("Invalid verification code", code="mfa_invalid")
    auth.user.mfa_enabled = True
    db.add(AuditLog(actor_id=auth.user.id, action="mfa_enabled", entity_type="user", entity_id=str(auth.user.id)))
    db.commit()
    return {"ok": True}


@router.post("/mfa/disable")
def mfa_disable(body: DisableMfaIn, auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    u = auth.user
    if not u.mfa_enabled:
        return {"ok": True}
    if not verify_password(body.password, u.password_hash) or not pyotp.TOTP(decrypt(u.mfa_secret_enc)).verify(body.code, valid_window=1):
        raise Unauthorized("Password or code is incorrect", code="mfa_invalid")
    u.mfa_enabled = False
    u.mfa_secret_enc = None
    db.add(AuditLog(actor_id=u.id, action="mfa_disabled", entity_type="user", entity_id=str(u.id)))
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(auth: AuthUser = Depends(get_auth_user), db=Depends(get_db)):
    memberships = db.execute(
        select(HouseholdMember, Household).join(Household, Household.id == HouseholdMember.household_id).where(HouseholdMember.user_id == auth.user.id).order_by(HouseholdMember.created_at)
    ).all()
    return {
        "user": user_out(auth.user),
        "households": [
            {"id": str(h.id), "name": h.name, "role": m.role, "base_currency": h.base_currency, "timezone": h.timezone, "is_demo": h.is_demo}
            for m, h in memberships
        ],
        "demo_mode": get_settings().demo_mode,
    }

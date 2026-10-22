import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# A hash that always fails, used to equalise timing for unknown emails.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def validate_password_strength(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if password.lower() == password or password.upper() == password:
        problems.append("both upper- and lower-case letters")
    if not any(c.isdigit() for c in password):
        problems.append("at least one digit")
    return problems


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(("enc:" + s.secret_key).encode()).digest()).decode()
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


# Short-lived signed links for private document downloads.
def sign_download(document_id: str, household_id: str, ttl_seconds: int) -> str:
    exp = int(time.time()) + ttl_seconds
    msg = f"{document_id}:{household_id}:{exp}"
    sig = hmac.new(get_settings().secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}:{sig}".encode()).decode().rstrip("=")


def verify_download(token: str) -> tuple[str, str] | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        document_id, household_id, exp, sig = base64.urlsafe_b64decode(padded.encode()).decode().split(":")
    except Exception:
        return None
    msg = f"{document_id}:{household_id}:{exp}"
    expected = hmac.new(get_settings().secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig) or int(exp) < int(time.time()):
        return None
    return document_id, household_id

import pyotp

from app.core.email import OUTBOX
from tests.conftest import User


def test_register_login_refresh_logout(client):
    u = User(client, "alice@example.com")
    assert client.cookies.get("ss_refresh")
    csrf = client.cookies.get("ss_csrf")
    r = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["access_token"]
    # refresh requires the CSRF header
    assert client.post("/api/v1/auth/refresh").status_code == 403
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies.get("ss_csrf")})
    assert r.status_code == 200
    # the session behind the old access token is revoked
    assert u.get("/transactions").status_code == 401


def test_weak_password_and_duplicate_email(client):
    r = client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "alllowercase1", "full_name": "X"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    User(client, "dup@example.com")
    r = client.post("/api/v1/auth/register", json={"email": "DUP@example.com", "password": "Str0ngPassw0rd!", "full_name": "Y"})
    assert r.status_code == 409


def test_login_lockout_after_failures(client):
    User(client, "lock@example.com")
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": "wrong"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": "Str0ngPassw0rd!"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_locked"


def test_unknown_email_gets_same_error(client):
    r = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_email_verification_required_when_enabled(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "require_email_verification", True)
    r = client.post("/api/v1/auth/register", json={"email": "v@example.com", "password": "Str0ngPassw0rd!", "full_name": "V"})
    assert r.json()["verification_required"] is True
    r = client.post("/api/v1/auth/login", json={"email": "v@example.com", "password": "Str0ngPassw0rd!"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    token = OUTBOX[-1]["body"].split("token=")[1].split()[0]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 422  # single use
    assert client.post("/api/v1/auth/login", json={"email": "v@example.com", "password": "Str0ngPassw0rd!"}).status_code == 200


def test_password_reset_revokes_sessions(client):
    u = User(client, "reset@example.com")
    assert client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"}).status_code == 200
    assert client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"}).status_code == 200
    token = OUTBOX[-1]["body"].split("token=")[1].split()[0]
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "N3wPassword!!"})
    assert r.status_code == 200
    assert u.get("/transactions").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "reset@example.com", "password": "N3wPassword!!"}).status_code == 200


def test_mfa_flow(client):
    u = User(client, "mfa@example.com")
    setup = u.post("/auth/mfa/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert u.post("/auth/mfa/enable", {"code": code}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": "mfa@example.com", "password": "Str0ngPassw0rd!"})
    assert r.json()["mfa_required"] is True
    bad = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "mfa@example.com", "password": "Str0ngPassw0rd!"})
    ok = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "code": pyotp.TOTP(setup["secret"]).now()})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_session_listing_and_revocation(client):
    u = User(client, "sess@example.com")
    sessions = u.get("/auth/sessions").json()
    assert len(sessions) == 1 and sessions[0]["current"]
    assert u.delete(f"/auth/sessions/{sessions[0]['id']}").status_code == 200
    assert u.get("/auth/sessions").status_code == 401


def test_data_isolation_between_users(user, other_user):
    t = user.payment("450.00", "ABC Restaurant")
    # other user cannot read, edit, void or list it
    assert other_user.get(f"/transactions/{t['id']}").status_code == 404
    assert other_user.patch(f"/transactions/{t['id']}", {"notes": "x"}).status_code == 404
    assert other_user.post(f"/transactions/{t['id']}/void", {}).status_code == 404
    assert other_user.get("/transactions").json()["total"] == 0
    # pointing X-Household-ID at someone else's household is forbidden
    r = other_user.get("/transactions", headers={"X-Household-ID": user.household_id})
    assert r.status_code == 403
    # cross-household references are rejected
    cats = user.get("/categories").json()
    r = other_user.post("/transactions", {"type": "expense", "occurred_on": "2026-10-18", "amount": "10", "category_id": cats[0]["id"]})
    assert r.status_code == 404
    assert other_user.dashboard()["gross_spending"] == "0.00"


def test_roles_viewer_is_read_only(client, user, other_user):
    r = user.post(f"/households/{user.household_id}/members", {"email": other_user.email, "role": "viewer"})
    assert r.status_code == 201, r.text
    hdr = {"X-Household-ID": user.household_id}
    assert other_user.get("/transactions", headers=hdr).status_code == 200
    r = other_user.post("/transactions", {"type": "expense", "occurred_on": "2026-10-18", "amount": "10"}, headers=hdr)
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_role"
    # member can write
    user.patch(f"/households/{user.household_id}/members/{other_user.user_id}", {"role": "member"})
    assert other_user.post("/transactions", {"type": "expense", "occurred_on": "2026-10-18", "amount": "10"}, headers=hdr).status_code == 201
    # last owner cannot be demoted
    r = user.patch(f"/households/{user.household_id}/members/{user.user_id}", {"role": "admin"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_owner"


def test_account_deletion_removes_data(client, user):
    user.payment("100.00", "Shop")
    r = user.delete("/me", json={"password": "Str0ngPassw0rd!", "confirm": "DELETE"})
    assert r.status_code == 200 and user.household_id in r.json()["deleted_households"]
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "Str0ngPassw0rd!"}).status_code == 401


def test_data_export_zip(user):
    import io
    import zipfile

    user.payment("100.00", "Shop")
    r = user.get("/me/export")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "canonical_transactions.json" in z.namelist()
    assert b"100.0000" in z.read("canonical_transactions.json")

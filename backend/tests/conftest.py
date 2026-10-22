"""Test harness: a real PostgreSQL 16 (embedded via pgserver, or TEST_DATABASE_URL), migrated with Alembic,
truncated between tests. Celery runs tasks inline."""
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="smartspend-test-"))

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "REQUIRE_EMAIL_VERIFICATION": "false",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "STORAGE_DIR": str(_TMP / "storage"),
        "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "OCR_PROVIDER": "none",
    }
)


def _database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    import pgserver

    data = ROOT / "var" / "pgtest"
    data.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(data), cleanup_mode=None)
    base = srv.get_uri()
    # A database per test run, so concurrent runs never interfere with each other. Leftovers from finished
    # runs are recognised by having no open connections (no process probing).
    name = f"smartspend_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as c:
        stale = c.execute(
            """select d.datname from pg_database d
               where d.datname like 'smartspend\\_test\\_%'
                 and not exists (select 1 from pg_stat_activity a where a.datname = d.datname)"""
        ).fetchall()
        for (old,) in stale:
            c.execute(f'drop database if exists "{old}"')
        c.execute(f'create database "{name}"')
    return base.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + f"/{name}"


DB_URL = _database_url()
os.environ["DATABASE_URL"] = DB_URL


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["url"] = DB_URL
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    yield
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_db():
    from sqlalchemy import text

    from app.core.db import Base, get_engine
    from app.core.email import OUTBOX
    from app.core.ratelimit import reset_rate_limits

    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    OUTBOX.clear()
    reset_rate_limits()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class User:
    """A registered, logged-in user with helpers that send auth + household headers."""

    def __init__(self, client, email: str, password: str = "Str0ngPassw0rd!"):
        self.c = client
        self.email = email
        r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": email.split("@")[0].title()})
        assert r.status_code == 201, r.text
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        self.token = r.json()["access_token"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {self.token}"}).json()
        self.household_id = me["households"][0]["id"]
        self.user_id = me["user"]["id"]

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}", "X-Household-ID": self.household_id}

    def get(self, path, **kw):
        return self.c.get(f"/api/v1{path}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, path, json=None, **kw):
        return self.c.post(f"/api/v1{path}", json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, path, json=None, **kw):
        return self.c.patch(f"/api/v1{path}", json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def put(self, path, json=None, **kw):
        return self.c.put(f"/api/v1{path}", json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def delete(self, path, **kw):
        return self.c.request("DELETE", f"/api/v1{path}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    # ---- domain helpers
    def tx(self, **kw):
        body = {"type": "expense", "occurred_on": "2026-10-18", "currency": "INR", **kw}
        body["amount"] = str(body["amount"])
        r = self.post("/transactions", body)
        assert r.status_code == 201, r.text
        return r.json()

    def bill(self, amount, merchant, on="2026-10-18", **kw):
        return self.tx(amount=amount, merchant_name=merchant, occurred_on=on, record_as="bill", **kw)

    def payment(self, amount, merchant, on="2026-10-18", **kw):
        return self.tx(amount=amount, merchant_name=merchant, occurred_on=on, payment_method=kw.pop("payment_method", "upi"), **kw)

    def candidates(self, **params):
        r = self.get("/reconciliation/candidates", params=params)
        assert r.status_code == 200, r.text
        return r.json()["items"]

    def dashboard(self, month="2026-10"):
        r = self.get(f"/dashboard/summary?month={month}")
        assert r.status_code == 200, r.text
        return r.json()["totals"]

    def txn(self, tx_id):
        return self.get(f"/transactions/{tx_id}").json()


@pytest.fixture
def user(client):
    return User(client, f"user-{uuid.uuid4().hex[:8]}@example.com")


@pytest.fixture
def other_user(client):
    return User(client, f"other-{uuid.uuid4().hex[:8]}@example.com")

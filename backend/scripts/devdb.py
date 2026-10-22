"""Starts a local PostgreSQL 16 (embedded via `pgserver`) for development without Docker.

Usage: python scripts/devdb.py            -> prints the DATABASE_URL and keeps running
The data directory is backend/var/pgdata. Docker Compose users do not need this.
"""
import os
import sys
import time
from pathlib import Path

import pgserver
import psycopg

DATA = Path(__file__).resolve().parents[1] / "var" / "pgdata"


def ensure(dbname: str = "smartspend") -> str:
    DATA.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(DATA), cleanup_mode=None)
    base = srv.get_uri()
    with psycopg.connect(base, autocommit=True) as c:
        if not c.execute("select 1 from pg_database where datname=%s", (dbname,)).fetchone():
            c.execute(f'create database "{dbname}"')
    return base.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + f"/{dbname}"


if __name__ == "__main__":
    url = ensure(sys.argv[1] if len(sys.argv) > 1 else "smartspend")
    print(url, flush=True)
    if "--once" not in sys.argv:
        while True:
            time.sleep(3600)

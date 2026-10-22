#!/usr/bin/env bash
# SmartSpend database helper: regenerate the schema script, back up, or restore.
#
#   database/scripts/db.sh schema                    # rebuild database/01_schema.sql from the migrations
#   database/scripts/db.sh backup                    # pg_dump to database/backups/smartspend-<time>.dump
#   database/scripts/db.sh restore database/backups/smartspend-20261022-1530.dump
#
# The connection comes from DATABASE_URL (the same variable the API uses), e.g.
#   postgresql+psycopg://smartspend:secret@localhost:5432/smartspend
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$ROOT/.venv/Scripts/python"
[ -x "$PYTHON" ] || PYTHON="python3"

url() {
  : "${DATABASE_URL:?Set DATABASE_URL first, e.g. postgresql+psycopg://smartspend:secret@localhost:5432/smartspend}"
  # libpq tools don't understand SQLAlchemy's '+driver' suffix.
  echo "$DATABASE_URL" | sed -E 's#^postgresql\+[a-z0-9]+://#postgresql://#'
}

case "${1:-}" in
  schema)
    out="$ROOT/database/01_schema.sql"
    # Offline mode writes SQL without connecting; the URL only selects the PostgreSQL dialect.
    sql="$(cd "$ROOT/backend" && DATABASE_URL="postgresql+psycopg://smartspend@localhost/smartspend" "$PYTHON" -m alembic upgrade head --sql 2>/dev/null)"
    {
      echo "-- SmartSpend: complete database schema (PostgreSQL 14+), generated from the Alembic migrations."
      echo "-- Do not edit by hand: change a migration, then run  database/scripts/db.sh schema"
      echo "-- Load into an empty database:  psql -d smartspend -v ON_ERROR_STOP=1 -f database/01_schema.sql"
      echo "-- Generated $(date '+%Y-%m-%d %H:%M')"
      echo
      echo "$sql"
    } > "$out"
    echo "Wrote $out"
    ;;
  backup)
    mkdir -p "$ROOT/database/backups"
    target="${2:-$ROOT/database/backups/smartspend-$(date +%Y%m%d-%H%M).dump}"
    pg_dump --format=custom --no-owner --file="$target" "$(url)"
    echo "Backup written to $target"
    ;;
  restore)
    file="${2:?Give the backup file to restore}"
    [ -f "$file" ] || { echo "No such file: $file" >&2; exit 1; }
    echo "This replaces every SmartSpend table in the target database with the backup's contents."
    read -r -p "Type RESTORE to continue: " answer
    [ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 0; }
    pg_restore --clean --if-exists --no-owner --single-transaction --dbname="$(url)" "$file"
    echo "Restored $file. Restart the API so it reconnects."
    ;;
  *)
    sed -n '2,9p' "$0"
    exit 1
    ;;
esac

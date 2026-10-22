# SmartSpend database scripts

Plain SQL and helper scripts for running SmartSpend on a PostgreSQL server you manage yourself. With Docker
Compose or `backend/scripts/dev.py` you don't need these: the database is created and migrated automatically.

| File | What it does | Changes data? |
|---|---|---|
| `00_create_database.sql` | Creates the `smartspend` login role and database (run as a superuser). Safe to run twice. | Creates role and database |
| `01_schema.sql` | The complete schema: 37 tables, indexes, constraints and the migration version. **Generated** from the Alembic migrations; don't edit it by hand. | Creates tables |
| `02_reset_data.sql` | Deletes every row but keeps the schema. Development and test only; needs `-v confirm=yes`. | **Deletes all data** |
| `03_reports.sql` | Read-only admin queries: workspaces, monthly net spending, matches to review, documents, card bills due soon, an integrity check and table sizes. | No |
| `scripts/db.ps1`, `scripts/db.sh` | `schema` regenerates `01_schema.sql`; `backup` runs `pg_dump`; `restore` runs `pg_restore` after confirmation. | `restore` replaces data |
| `backups/` | Where `backup` writes `smartspend-<yyyyMMdd-HHmm>.dump` files. Git ignores this folder. | — |

## New server, step by step

```powershell
# 1. Role and database (as a PostgreSQL superuser)
psql -U postgres -v app_password=choose-a-strong-password -f database/00_create_database.sql

# 2. Schema
psql -U smartspend -d smartspend -v ON_ERROR_STOP=1 -f database/01_schema.sql

# 3. Point the API at it (backend/.env or the environment) and start it
DATABASE_URL=postgresql+psycopg://smartspend:choose-a-strong-password@localhost:5432/smartspend
```

Default categories and the "Cash" account are created per workspace when someone signs up, so there is no
reference data to load. For sample data, start the API with `DEMO_MODE=true` (see `backend/scripts/seed_demo.py`).

**Schema script or migrations?** Both produce the same database. `01_schema.sql` is convenient for a DBA or a
fresh server. Existing databases should be upgraded with migrations (`cd backend && python -m alembic upgrade
head`), which also run any data changes. The schema script records the migration version, so later
`alembic upgrade head` runs continue from the right place.

## Backups

All commands read `DATABASE_URL`, the same setting the API uses (the `+psycopg` part is handled for you).

```powershell
.\database\scripts\db.ps1 backup                                   # Windows
.\database\scripts\db.ps1 restore database\backups\smartspend-20261022-1340.dump
```

```bash
database/scripts/db.sh backup                                      # macOS / Linux
database/scripts/db.sh restore database/backups/smartspend-20261022-1340.dump
```

Backups use `pg_dump`'s custom format with `--no-owner`, so they restore into a database owned by a different
role. A restore runs in a single transaction: it either fully succeeds or changes nothing. Uploaded bill files
live in object storage (`STORAGE_DIR` or S3), not in the database, so back that up as well.

On Windows without the PostgreSQL client tools installed, the scripts use the embedded PostgreSQL binaries that
`dev.py` installs into `.venv`.

## After changing a migration

```powershell
.\database\scripts\db.ps1 schema      # or: database/scripts/db.sh schema
```

This regenerates `01_schema.sql` from the migrations without connecting to any database. Commit it together
with the migration.

## Naming

The app shows "workspaces"; the database tables are `households` and `household_members`. The API and
schema keep the original names so existing integrations keep working.

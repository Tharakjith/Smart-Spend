# Deployment guide

The reference deployment is `docker-compose.yml`. It maps one-to-one onto any container platform (ECS,
Kubernetes, Nomad): the same images, with managed PostgreSQL, Redis and object storage substituted.

## Components

| Service | Image | Scale | Notes |
|---|---|---|---|
| `web` | `frontend/Dockerfile` (nginx) | ≥2 | Serves the SPA and proxies `/api` to `api` |
| `api` | `backend/Dockerfile` | ≥2 | Stateless; uvicorn with 4 workers per container |
| `worker` | backend image, `celery worker` | ≥1 | OCR, extraction, imports and checks; idempotent and retry-safe |
| `beat` | backend image, `celery beat` | **exactly 1** | Schedules notification checks |
| `migrate` | backend image, `alembic upgrade head` | one-off | Runs before new api/worker containers start |
| PostgreSQL 16 | managed | HA pair | Point-in-time recovery enabled |
| Redis 7 | managed | 1 | Celery broker and rate-limit counters (no durable business data) |
| Object storage | S3 / MinIO | n/a | Private bucket, block public access, versioning on |

## Steps

1. `cp .env.example .env` and fill every `CHANGE_ME`:
   - `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
   - `ENCRYPTION_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - database and object-storage passwords, `FRONTEND_URL`, `CORS_ORIGINS`, and SMTP settings
2. Terminate TLS in front of `web` (load balancer, Caddy or Traefik) and keep `COOKIE_SECURE=true`.
   The API sends HSTS when `ENVIRONMENT=production`.
3. `docker compose up -d --build`. `migrate` runs first; `api`, `worker` and `beat` wait for it.
4. Check `GET /api/health` (it checks database connectivity) and sign up through the UI.

Startup refuses unsafe production configuration: default or short `SECRET_KEY`, missing `ENCRYPTION_KEY`,
`COOKIE_SECURE=false`, or `DEMO_MODE=true`.

## Storage encryption

- **AWS S3:** set `S3_SSE=AES256` (or use bucket-default SSE-KMS), enable Block Public Access and versioning.
- **Bundled MinIO:** it has no KMS, so keep `S3_SSE` empty and put the MinIO volume on an encrypted disk
  (LUKS/EBS encryption), or configure MinIO KMS and set `S3_SSE=AES256`.
- **PostgreSQL:** use storage-level encryption (managed services do this by default) and require TLS
  (`?sslmode=require` in `DATABASE_URL`).

## Backups and recovery

| Data | Method | Suggested policy |
|---|---|---|
| PostgreSQL | Managed PITR, plus a nightly `pg_dump -Fc` copied to a separate account or region | 35 days PITR, 12 monthly dumps |
| Documents | Bucket versioning plus cross-region replication (or `mc mirror` for MinIO) | Keep as long as the transactions they back |
| Secrets | Secret manager with versioning | n/a |

Restore drill (run quarterly):

```bash
pg_restore --clean --no-owner -d "$DATABASE_URL" smartspend-YYYYMMDD.dump
docker compose run --rm migrate              # brings the schema to head if the dump is older
# then POST /api/v1/reconciliation/recalculate per household (or run the regenerate task) to re-verify counted amounts
```

Documents are referenced by random storage keys, so a database restore needs the matching bucket state; restore
both to the same point in time.

## Upgrades

1. Build the new images.
2. Run `migrate` (Alembic migrations are written to be backward compatible with the previous API version).
3. Roll `api` and `worker`, then restart `beat`.

Roll back by redeploying the previous images. Downgrade migrations only if the new schema is incompatible:
`alembic downgrade -1`.

## Monitoring

- Health: `GET /api/health`, plus container healthchecks (`api` has one built in).
- Logs: JSON-friendly stdout; every response carries `X-Request-ID`, which is also included in error bodies.
- Alert on: 5xx rate, worker queue depth (Redis `LLEN celery`), documents stuck in `processing` for more than
  15 minutes, failed jobs (`document_processing_jobs.status='failed'`), and backup job failures.
- Data integrity: `POST /api/v1/reconciliation/recalculate` reports `amount_drift_corrected`, which should always
  be empty. Run it periodically and alert on any drift.

# Development setup

## Prerequisites

- Python 3.11+ and Node.js 20+ (22 recommended)
- OCR for photos, screenshots and scanned PDFs works out of the box: `requirements.txt` includes **RapidOCR**,
  a pip package with bundled models (no system install, works on Windows). If Tesseract is installed it is
  used instead (`OCR_PROVIDER=auto`). Force one with `OCR_PROVIDER=rapidocr` or `tesseract`, or set `none` to
  disable OCR.
- Docker is **not** required for development. `scripts/dev.py` starts an embedded PostgreSQL 16 (via `pgserver`)
  under `backend/var/pgdata`.

## First run

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt      # .venv/bin/pip on macOS/Linux
cd frontend && npm install && npx playwright install chromium   # Playwright only needed for e2e tests
```

Run the two servers in separate terminals:

```bash
cd backend && ../.venv/Scripts/python scripts/dev.py    # API  http://127.0.0.1:8000  (docs at /api/docs)
cd frontend && npm run dev                              # Web  http://127.0.0.1:5173
```

`dev.py` starts Postgres, runs `alembic upgrade head`, optionally seeds demo data, and starts the API. It
restarts the API automatically when a file under `backend/app/` changes. It does this with its own
supervisor rather than `uvicorn --reload`, because uvicorn's reloader can hang on Windows. On a change, the
whole server process tree is stopped, the port is confirmed free, and a fresh server starts. New migration
files are not applied automatically (they're usually still being edited): run `python -m alembic upgrade head`
when ready.

| Variable | Effect |
|---|---|
| `DATABASE_URL` | Use an existing PostgreSQL instead of the embedded one |
| `DEMO_MODE=true` | Seed the labelled demo household (`demo@example.com` / `DemoPassw0rd!`) |
| `DEV_RELOAD=false` | Turn off auto-reload (it is on by default) |
| `REQUIRE_EMAIL_VERIFICATION` | Defaults to `false` under `dev.py`. Verification links are printed to the API log when SMTP is not set |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `120` under `dev.py` so the browser tests can sign up many accounts (the normal default is 10) |

### Sending real email (password-reset codes, verification)

Without SMTP, nothing leaves the machine: emails are written to the API log, and in development the
"Forgot password" page shows the reset code on screen. To deliver real emails, create `backend/.env`
(or `.env` in the repo root) with your provider's SMTP settings. For Gmail, turn on 2-Step Verification and
create an *app password* (Google Account → Security → App passwords); your normal Gmail password won't work.

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcdefghijklmnop   # the 16-character app password, no spaces
SMTP_FROM=SmartSpend <you@gmail.com>
```

Port 587 uses STARTTLS and port 465 uses implicit TLS. Restart the API after editing `.env` (settings are read at
startup). If sending fails, the request still succeeds and the API log records the SMTP error.

In development, background jobs (OCR, extraction) run inline (`CELERY_TASK_ALWAYS_EAGER=true`), so Redis isn't
needed. To run a real worker: start Redis, set `CELERY_TASK_ALWAYS_EAGER=false`, and run
`celery -A app.core.celery_app worker` and `celery -A app.core.celery_app beat`.

## Configuration reference

All settings are environment variables (or a `.env` file in the repo root or `backend/`); see
`backend/app/core/config.py`. Production refuses to start with default secrets, insecure cookies or demo mode.

| Setting | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` enables strict checks and HSTS |
| `SECRET_KEY` | dev value | JWT and download-link signing key; 32+ random characters in production |
| `ENCRYPTION_KEY` | derived (dev only) | Fernet key for MFA secrets |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | 15 / 14 | Session lifetimes |
| `COOKIE_SECURE` | `false` | Must be `true` behind HTTPS |
| `STORAGE_BACKEND` | `local` | `local` (`STORAGE_DIR`) or `s3` (`S3_*`; `S3_SSE` for server-side encryption) |
| `MAX_UPLOAD_BYTES` | 15 MB | Per-file limit |
| `MALWARE_SCANNER` | `none` | `clamav` uses `CLAMAV_HOST`/`CLAMAV_PORT` and fails closed if unreachable |
| `OCR_PROVIDER` / `TESSERACT_CMD` | `auto` / auto | `auto` uses Tesseract if installed, else RapidOCR; `none` disables OCR (images then need manual entry) |
| `AI_PROVIDER` / `AI_ALLOW_DOCUMENT_SHARING` | `none` / `false` | See docs/SECURITY.md before enabling |
| `RATE_LIMIT_AUTH_PER_MINUTE` | 10 | Per IP and endpoint, for auth routes |

## Sample fixtures

`python -m scripts.make_fixtures` (from `backend/`) writes sample files to `backend/fixtures/`:

- grocery, restaurant, pharmacy and fuel receipts, and an electricity bill (PDF)
- a UPI payment screenshot (PNG; needs OCR)
- a bank statement CSV that matches several of the receipts, and a credit card statement (XLSX)
- `statement-ambiguous-matches.csv`, which exercises the matcher's hard cases: the same merchant and amount on
  different days, a tip, one payment covering two invoices, and a reversal

Suggested walkthrough: upload `receipt-freshmart-grocery.pdf`, confirm it, then import `statement-bank-xyz.csv`.
The UPI row is suggested as a high-confidence match (same UPI reference). Confirm it, and the dashboard counts
₹595 once.

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest           # embedded Postgres; or set TEST_DATABASE_URL
cd frontend && npx vitest run && npx tsc -b
cd frontend && npx playwright test                         # with both dev servers running
```

Each pytest run creates its own throwaway database, so parallel runs don't interfere.

## Troubleshooting

- **Port 8000 busy:** another API instance is running; stop it or set `PORT=8001` (and `VITE_API_PROXY`).
- **Images stay in "Needs review" with an OCR message:** no OCR engine is available. Run
  `pip install -r backend/requirements.txt` (installs RapidOCR), then click **Re-run extraction** on the document.
- **Photos of curled or folded bills:** if the first read finds no total or date, the image is re-read straightened
  to the angles its text runs at. Values found that way are marked "please check" on the review screen; nothing
  is guessed.
- **Login says "Account temporarily locked":** five failed attempts lock the account for 15 minutes.
- **Embedded Postgres won't start:** delete `backend/var/pgdata` (this erases local data) or point `DATABASE_URL`
  at your own PostgreSQL 16.

# SmartSpend

Expense management that counts every purchase **once**. Upload bills and receipts, import bank, card and UPI
statements, record cash and person-to-person payments. SmartSpend recognises when a bill and a payment (or two
copies of the same payment) describe the same real-world event. It explains why it thinks so, and keeps your
totals accurate only after you confirm.

- **Reconciliation engine:** an explainable, deterministic scoring of references, amounts, dates and merchants.
  Many-to-many allocations (partial payments, one payment covering several bills), duplicate merges, refunds and
  reversals. Every action can be undone and is audited.
- **Canonical ledger:** dashboards and reports read reconciled records, never a blind sum of documents.
- **Document intelligence:** PDF text extraction, OCR, a receipt/invoice/UPI-screenshot parser with confidence
  scores and validation, line items, and price history. Missing values are never invented.
- **Statement import:** CSV, XLSX and PDF, with column mapping, preview and row fingerprints, so the same statement
  imported twice adds nothing.
- **Credit card bills:** limits, statements (total and minimum due, due date, interest and fees), paying or
  linking payments, paid/minimum/overdue status, utilization, unbilled spend and due-date reminders. Card
  purchases count as spending once; paying the bill is a transfer.
- **People, loans and shared bills, budgets, savings goals, recurring payments, notifications,** and reports
  exportable to CSV, Excel and PDF.
- **Security:** Argon2id passwords, rotating refresh sessions, optional TOTP MFA, roles, household isolation,
  private signed document links, rate limiting, upload validation and optional malware scanning.

| | |
|---|---|
| Backend | Python 3.11 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · Celery + Redis |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS 4 · shadcn-style components · TanStack Query · Recharts |
| Documents | PyMuPDF · pdfplumber · Tesseract OCR · ReportLab · openpyxl |

## Quick start

### Option A: local development (no Docker needed)

Requires Python 3.11+ and Node 20+. PostgreSQL runs embedded through `pgserver`.

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt     # Windows (use .venv/bin/pip on macOS/Linux)
cd frontend && npm install && cd ..

# Terminal 1: API on :8000 (starts Postgres, applies migrations)
cd backend && ../.venv/Scripts/python scripts/dev.py

# Terminal 2: web app on :5173 (proxies /api to :8000)
cd frontend && npm run dev
```

Open http://localhost:5173 and create an account. Email verification is off in local development. For a
pre-filled **demo household** (clearly labelled as sample data), start the API with `DEMO_MODE=true` and sign in
as `demo@example.com` / `DemoPassw0rd!`.

### Option B: Docker Compose (production-like)

```bash
cp .env.example .env          # set SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD
docker compose up --build     # http://localhost:8080
```

This runs PostgreSQL, Redis, MinIO (a private document bucket), the API, a Celery worker and beat, and nginx
serving the web app. Add `--profile scan` and `MALWARE_SCANNER=clamav` to scan uploads with ClamAV.

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest          # 100 tests on real PostgreSQL
cd frontend && npx vitest run && npx tsc -b               # unit tests + typecheck
cd frontend && npx playwright test                        # browser E2E (needs both dev servers running)
```

The backend suite covers specification Scenarios A–J, concurrency (parallel confirms and over-allocation races),
duplicate statement imports, authentication and data isolation, upload security, monetary precision, month-end
boundaries, reports and an end-to-end journey. In that journey, the computed account balance must equal the bank
statement's closing balance.

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, ER diagram, source vs canonical records, matching algorithm, calculation rules, API contracts |
| [docs/SETUP.md](docs/SETUP.md) | Development setup, configuration reference, sample fixtures, troubleshooting |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Production deployment, HTTPS, backups and restore, upgrades, monitoring |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, controls, privacy and AI data handling, retention |
| [docs/API.md](docs/API.md) | API conventions and examples; interactive docs at `/api/docs` |

## Repository layout

```
backend/   FastAPI app (app/modules/<domain>), Alembic migrations, tests, scripts (dev server, demo seed, fixtures)
frontend/  React app (src/pages, src/components), Playwright e2e
docs/      Architecture, setup, deployment, security and API docs
docker-compose.yml, .env.example, .github/workflows/ci.yml
```

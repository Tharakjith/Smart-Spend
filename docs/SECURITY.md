# Security and privacy

SmartSpend stores sensitive financial data. This document lists what is protected, how, and what operators must
configure.

## Authentication and sessions

- Passwords are hashed with **Argon2id** (`argon2-cffi`). Passwords need 10+ characters with mixed case and a
  digit. Unknown emails get the same error and similar timing as wrong passwords.
- **Lockout:** 5 failed logins lock the account for 15 minutes. Auth endpoints are rate-limited per IP (Redis
  in production).
- **Tokens:** a 15-minute JWT access token is held in memory only (never in localStorage). The refresh token is
  an opaque random value in an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth`, stored
  **hashed**, rotated on every use, and revocable per session (Settings → Security).
- **CSRF:** cookie-authenticated endpoints (`/auth/refresh`, `/auth/logout`) require a double-submit
  `X-CSRF-Token`. All other API calls use the bearer token, which browsers never attach automatically.
- **Email verification and password reset** use single-use, hashed, expiring tokens (48 h and 1 h). A reset
  revokes every session. The reset email also carries a 6-digit code: stored only as a hash bound to its token
  row, valid 15 minutes, dead after 5 wrong guesses, and replaced by any newer request. Using the code or the
  link spends both. Unknown addresses get the same response and the same "invalid code" error. The
  `/auth/dev-mailbox` endpoint that shows codes on screen exists only when `ENVIRONMENT=development` and SMTP is
  not configured.
- **MFA:** optional TOTP. Secrets are encrypted at rest with Fernet (`ENCRYPTION_KEY`).

## Authorization and isolation

- Every financial row carries a `household_id`. Every request resolves the household from membership
  (`X-Household-ID` must be one the user belongs to) and every lookup checks ownership; objects from other
  households return 404, not 403.
- Roles: **owner** (everything, including ownership), **admin** (members and settings), **member** (read and
  write data), **viewer** (read only). They are enforced in the backend; the UI only hides controls. A household
  always keeps at least one owner.
- Tests cover cross-household reads, writes, references and header spoofing (`tests/test_auth.py`).

## Documents and uploads

- Size limit (15 MB), magic-byte content sniffing that must agree with the extension, structural validation
  (PDF parse, encrypted-PDF rejection, a page limit, image verification, a decompression-bomb guard) and optional
  **ClamAV** scanning, which fails closed when the scanner is unreachable.
- Files are stored under random keys in a private directory or bucket that is never web-served. Downloads go
  through **5-minute HMAC-signed links** bound to the document and household, served with `no-store`, `nosniff`
  and a restrictive CSP (images additionally sandboxed).
- Exact duplicates are detected by SHA-256 per household. A confirmed document can't be deleted while a
  transaction relies on it (archive instead).

## Financial integrity controls

- Money is `NUMERIC(19,4)` in PostgreSQL and `Decimal` in Python. The API rejects floats in the money layer and
  serialises amounts as strings.
- CHECK constraints (non-negative amounts, `allocated ≤ amount`, `counted ≤ amount`) and unique and partial-unique
  indexes (one active allocation per pair, one match per unordered pair, statement-row fingerprints, document
  hashes) back up the application logic. Reconciliation locks rows in a fixed order. `Idempotency-Key` is
  supported on financial POSTs.
- Nothing is hard-deleted once confirmed. Voids, merges and unlinks are reversible and logged in `audit_logs` and
  `reconciliation_audit_logs` (actor, time, before and after).

## Never stored

UPI PINs, banking or net-banking passwords, card numbers (only an optional last 4 digits), CVV/CVC, and OTPs. No
screen or form asks for them.

## AI and third parties

- AI is **off by default**. It requires all three of: `AI_PROVIDER=anthropic`, `AI_ALLOW_DOCUMENT_SHARING=true`
  (an operator decision), and the household's own opt-in (Settings → Household).
- When enabled, only **extracted text** is sent (never the image or PDF), and only for fields the deterministic
  parser couldn't find, or for categorising a transaction no rule matched.
- AI suggestions can't fabricate figures: values that don't appear in the document text are discarded. They are
  labelled as AI suggestions and still need the user's review. AI never links, merges or confirms records.
- Operators enabling AI must update their privacy notice and confirm the provider's data-handling terms
  (retention, region) meet their obligations.

## Transport and headers

HTTPS is terminated at the edge (see DEPLOYMENT.md). The API sets `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, `Permissions-Policy`, `Cache-Control: no-store` for API responses, and HSTS in production;
nginx adds a CSP for the SPA. CORS is limited to `CORS_ORIGINS`.

## Data rights and retention

- **Export:** Settings → Data & privacy → Download export (a ZIP of all household records as JSON, plus the
  original documents). Owners and admins only.
- **Deletion:** Settings → Delete account. This removes the user, every household where they are the only
  member, and those households' stored files. It is blocked when the user is the last owner of a shared
  household.
- **Retention:** recommended defaults are to keep financial records while the account exists, keep audit logs
  for 7 years where tax rules require it, and keep server logs for 30 days. Unconfirmed uploads and abandoned
  imports can be purged after 90 days (`DELETE /documents/{id}`, `DELETE /imports/{id}`).

## Reporting vulnerabilities

Report security issues privately to the maintainers. Don't open a public issue.

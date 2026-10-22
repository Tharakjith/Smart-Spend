# API guide

Interactive OpenAPI docs: **`/api/docs`** (Swagger UI) and `/api/redoc`; the schema is at `/api/openapi.json`.
The endpoint list is in [ARCHITECTURE.md §6](ARCHITECTURE.md#6-api-contracts-summary).

## Conventions

- Base path `/api/v1`, JSON bodies, UTF-8.
- **Auth:** `Authorization: Bearer <access_token>` from `POST /auth/login`. Refresh with `POST /auth/refresh`
  (cookie plus `X-CSRF-Token`).
- **Household:** `X-Household-ID: <uuid>` selects the household; it defaults to the user's first.
- **Money:** amounts are **decimal strings** in requests and responses (`"450.00"`). Floats are rejected by the
  money layer.
- **Dates:** `occurred_on` is a calendar date in the household's timezone (`YYYY-MM-DD`). Timestamps are ISO-8601
  UTC.
- **Pagination:** `?page=1&page_size=50` (max 200) returns `{items, total, page, page_size}`.
- **Idempotency:** send `Idempotency-Key: <uuid>` on POSTs that create financial effects (transactions, confirm,
  manual match, allocate). A replay returns the original response; reusing a key with a different body returns
  409.
- **Errors:** always this shape:

```json
{"error": {"code": "allocation_exceeds_payment", "message": "Allocation ₹900.00 exceeds the payment's unallocated balance ₹600.00", "details": {"available": "600.0000"}, "request_id": "4f0c…"}}
```

Common codes: `validation_failed` (422), `not_found` (404), `insufficient_role` (403), `version_conflict` and
`constraint_violation` (409), `rate_limited` (429), `duplicate_document` (409, with `existing_document_id`).

## Example: a receipt and its UPI payment, counted once

```bash
API=http://localhost:8000/api/v1
TOKEN=$(curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"…"}' | jq -r .access_token)
H="Authorization: Bearer $TOKEN"

# The bill (evidence of purchase)
curl -s $API/transactions -H "$H" -H 'Content-Type: application/json' \
  -d '{"type":"expense","occurred_on":"2026-10-18","amount":"450.00","merchant_name":"ABC Restaurant","record_as":"bill"}'

# The UPI payment (evidence of money moving)
curl -s $API/transactions -H "$H" -H 'Content-Type: application/json' \
  -d '{"type":"expense","occurred_on":"2026-10-18","amount":"450.00","merchant_name":"ABC RESTAURANT","payment_method":"upi"}'

# The engine's suggestion, with reasons
curl -s "$API/reconciliation/candidates" -H "$H" | jq '.items[0] | {id, confidence, score, reasons: [.reasons[].text]}'
# => {"confidence":"high","score":80,"reasons":["Same transaction date","Same merchant (ABC Restaurant)","Amounts match exactly (₹450.00)"]}

curl -s -X POST "$API/reconciliation/<match_id>/confirm" -H "$H" -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen)" -d '{}'
curl -s "$API/dashboard/summary?month=2026-10" -H "$H" | jq .totals.gross_spending    # "450.00"
```

## Example: one payment settling two invoices

```bash
curl -s $API/reconciliation/allocate-payment -H "$H" -H 'Content-Type: application/json' -d '{
  "payment_transaction_id": "<payment>",
  "allocations": [
    {"bill_transaction_id": "<invoice A>", "amount": "900.00"},
    {"bill_transaction_id": "<invoice B>", "amount": "600.00"}
  ]}'
```

The request is atomic: if the total exceeds the payment's unallocated balance, nothing is applied (409
`allocation_exceeds_payment`).

## Reports

`GET /reports/{kind}?date_from=&date_to=&format=json|csv|xlsx|pdf`, where `kind` is one of `transactions`,
`monthly`, `annual`, `category`, `merchant`, `person`, `budget`, `items`, `loans`, `unmatched`, `duplicates`,
`reconciliation`. Every export states its date range, currency and filters. CSV cells that could be read as
spreadsheet formulas are neutralised.

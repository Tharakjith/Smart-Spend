"""Every sample bill through the real pipeline: upload -> extract -> review -> confirm -> categorised ledger entry."""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

CASES = [
    # file, merchant, date, total, invoice no., line items, payment method, category after confirm
    ("receipt-freshmart-grocery.pdf", "FRESH MART SUPERMARKET", "2026-10-18", "595.00", "FM-20481", 5, "upi", "Groceries"),
    ("receipt-abc-restaurant.pdf", "ABC Restaurant", "2026-10-18", "450.00", "ABC/2026/7781", 3, "cash", "Restaurants"),
    ("receipt-apollo-pharmacy.pdf", "APOLLO PHARMACY", "2026-10-15", "247.00", "AP-55102", 3, "debit_card", "Medicines"),
    ("receipt-indian-oil-fuel.pdf", "INDIAN OIL - SREE KRISHNA FUELS", "2026-10-12", "2136.00", "004512", 1, "upi", "Fuel"),
    ("bill-kseb-electricity.pdf", "KERALA STATE ELECTRICITY BOARD", "2026-10-05", "1840.00", "KSEB/OCT/88213", 3, None, "Electricity"),
]


@pytest.mark.parametrize("name,merchant,day,total,invoice,n_items,method,category", CASES, ids=[c[0] for c in CASES])
def test_bill_fixture_end_to_end(user, name, merchant, day, total, invoice, n_items, method, category):
    data = (FIXTURES / name).read_bytes()
    r = user.post("/documents", files={"file": (name, data, "application/pdf")})
    assert r.status_code == 201, r.text
    doc = user.get(f"/documents/{r.json()['id']}").json()
    assert doc["status"] == "needs_review"
    f = doc["extraction"]["fields"]
    assert f["merchant_name"]["value"] == merchant
    assert f["date"]["value"] == day
    assert f["total"]["value"] == total
    assert f["invoice_number"]["value"] == invoice
    assert f["payment_method"]["value"] == method
    assert len(doc["extraction"]["line_items"]) == n_items
    assert not [i for i in doc["extraction"]["validation"] if i["level"] == "error"], doc["extraction"]["validation"]

    # Confirm with category left on "Auto", the way the review screen sends it.
    items = [{k: i[k] for k in ("name", "quantity", "unit", "unit_price", "line_total")} for i in doc["extraction"]["line_items"]]
    r = user.post(
        f"/documents/{doc['id']}/confirm",
        {"merchant_name": merchant, "occurred_on": day, "amount": total, "invoice_number": invoice, "payment_method": method, "doc_kind": "invoice", "line_items": items},
    )
    assert r.status_code == 200, r.text
    tx = r.json()["transaction"]
    assert tx["category_name"] == category
    assert tx["amount"] == total  # same precision on create and on every later read
    assert tx["sources"][0]["role"] == "bill" and tx["sources"][0]["document_id"] == doc["id"]
    # Line items add up exactly where the bill has no tax/discount adjustments.
    assert len(tx["line_items"]) == n_items


def test_all_bills_count_once_in_the_month(user):
    for name, merchant, day, total, invoice, *_ in CASES:
        doc = user.post("/documents", files={"file": (name, (FIXTURES / name).read_bytes(), "application/pdf")}).json()
        user.post(f"/documents/{doc['id']}/confirm", {"merchant_name": merchant, "occurred_on": day, "amount": total, "invoice_number": invoice, "doc_kind": "invoice"})
    t = user.dashboard()
    assert t["gross_spending"] == "5268.00"  # 595 + 450 + 247 + 2136 + 1840
    cats = {c["name"]: c["amount"] for c in user.get("/analytics/categories?month=2026-10").json()}
    assert cats == {
        "Transportation and Fuel": "2136.00",
        "Electricity and Utilities": "1840.00",
        "Groceries": "595.00",
        "Food and Dining": "450.00",
        "Healthcare and Medicines": "247.00",
    }

from decimal import Decimal

from app.modules.documents.parser import parse_document
from tests.factories import GROCERY_RECEIPT, RESTAURANT_RECEIPT, UPI_SCREENSHOT_TEXT, receipt_pdf


def v(parsed, key):
    return parsed["fields"][key]["value"]


# ---------------------------------------------------------------- parser
def test_grocery_receipt_extraction():
    p = parse_document("\n".join(GROCERY_RECEIPT))
    assert p["kind"] == "invoice"
    assert v(p, "merchant_name") == "FRESH MART SUPERMARKET"
    assert v(p, "date") == "2026-10-18" and v(p, "time") == "19:42:00"
    assert v(p, "total") == "595.00" and v(p, "subtotal") == "600.00"
    assert v(p, "discount") == "20.00" and v(p, "tax") == "15.00"
    assert v(p, "invoice_number") == "FM-20481"
    assert v(p, "payment_method") == "upi" and v(p, "payment_reference") == "429187654321"
    assert v(p, "gstin") == "32ABCDE1234F1Z5"
    names = [i["name"] for i in p["line_items"]]
    assert names == ["Rice Ponni 5kg", "Milk 1L", "Bread Brown", "Lifebuoy Soap", "Surf Excel Detergent 1kg"]
    rice = p["line_items"][0]
    assert rice["quantity"] == "5" and rice["unit"] == "kg" and rice["line_total"] == "320.00"
    assert [i for i in p["validation"] if i["level"] == "error"] == []


def test_restaurant_receipt_with_service_charge_validates():
    p = parse_document("\n".join(RESTAURANT_RECEIPT))
    assert v(p, "total") == "450.00" and v(p, "charges") == "10.00"
    assert v(p, "payment_method") == "cash"
    assert not [i for i in p["validation"] if i["code"] == "total_mismatch"]


def test_upi_screenshot_text():
    p = parse_document(UPI_SCREENSHOT_TEXT)
    assert p["kind"] == "upi_screenshot"
    assert v(p, "merchant_name") == "ABC Restaurant" and v(p, "total") == "450"
    assert v(p, "payment_reference") == "429112345678" and v(p, "date") == "2026-10-18"


def test_missing_values_are_never_fabricated():
    p = parse_document("SOME SHOP\nThanks for visiting\n")
    assert v(p, "total") is None and v(p, "date") is None and v(p, "currency") is None
    assert {i["code"] for i in p["validation"]} >= {"total_missing", "date_missing"}
    assert p["line_items"] == []


def test_total_mismatch_is_flagged():
    p = parse_document("SHOP\n18/10/2026\nItem A    100.00\nItem B    50.00\nSub Total   150.00\nGrand Total  180.00\n")
    assert "total_mismatch" in {i["code"] for i in p["validation"]}


def test_failed_upi_payment_flagged():
    p = parse_document("Payment failed\n₹300\nPaid to\nRahul\n18 Oct 2026\nUPI transaction ID: 429100000009")
    assert "payment_not_completed" in {i["code"] for i in p["validation"]}


# ---------------------------------------------------------------- upload pipeline
def upload(user, name, data, kind=None):
    return user.post("/documents", files={"file": (name, data, "application/octet-stream")}, data={"doc_kind": kind} if kind else None)


def test_upload_extract_confirm_and_match_with_upi(user):
    pdf = receipt_pdf(GROCERY_RECEIPT)
    r = upload(user, "freshmart.pdf", pdf)
    assert r.status_code == 201, r.text
    doc = user.get(f"/documents/{r.json()['id']}").json()
    assert doc["status"] == "needs_review"
    assert doc["extraction"]["method"] == "pdf_text"
    f = doc["extraction"]["fields"]
    assert f["total"]["value"] == "595.00" and f["merchant_name"]["value"] == "FRESH MART SUPERMARKET"
    assert len(doc["extraction"]["line_items"]) == 5

    body = {
        "merchant_name": f["merchant_name"]["value"],
        "occurred_on": f["date"]["value"],
        "occurred_time": f["time"]["value"],
        "amount": f["total"]["value"],
        "currency": "INR",
        "doc_kind": "invoice",
        "invoice_number": f["invoice_number"]["value"],
        "payment_reference": f["payment_reference"]["value"],
        "line_items": [{k: i[k] for k in ("name", "quantity", "unit", "unit_price", "line_total")} for i in doc["extraction"]["line_items"]],
    }
    r = user.post(f"/documents/{doc['id']}/confirm", body)
    assert r.status_code == 200, r.text
    tx = r.json()["transaction"]
    assert tx["category_name"] == "Groceries"
    # confirming twice is idempotent
    r2 = user.post(f"/documents/{doc['id']}/confirm", body)
    assert r2.json()["transaction"]["id"] == tx["id"]

    # the UPI payment imported later matches by exact reference and counts once
    user.payment("595.00", "FRESHMART TRIVANDRUM", upi_txn_id="429187654321", on="2026-10-18")
    m = user.candidates()[0]
    assert m["confidence"] == "high" and "shared_reference" in {x["code"] for x in m["reasons"]}
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    assert user.dashboard()["gross_spending"] == "595.00"

    # price history records each item with its source
    h = user.get("/prices/history?product=rice ponni 5kg").json()
    obs = h["series"][0]["observations"][0]
    assert obs["unit_price"] == "64.00" and obs["price_unit"] == "kg" and obs["document_id"] == doc["id"]


def test_duplicate_upload_is_blocked_and_reported(user):
    pdf = receipt_pdf(RESTAURANT_RECEIPT)
    first = upload(user, "abc.pdf", pdf)
    assert first.status_code == 201
    second = upload(user, "abc-copy.pdf", pdf)
    assert second.status_code == 409 and second.json()["error"]["code"] == "duplicate_document"
    assert second.json()["error"]["details"]["existing_document_id"] == first.json()["id"]
    q = user.get("/reconciliation/queues").json()
    assert q["duplicate_uploads"][0]["attempted_filename"] == "abc-copy.pdf"
    assert user.get("/documents").json()["total"] == 1


def test_same_file_allowed_in_different_households(user, other_user):
    pdf = receipt_pdf(RESTAURANT_RECEIPT)
    assert upload(user, "a.pdf", pdf).status_code == 201
    assert upload(other_user, "a.pdf", pdf).status_code == 201


def test_upload_security_validation(user):
    assert upload(user, "evil.pdf", b"MZ\x90\x00 this is a windows executable").json()["error"]["code"] == "unsupported_type"
    assert upload(user, "receipt.png", receipt_pdf(["x"])).json()["error"]["code"] == "extension_mismatch"
    assert upload(user, "broken.pdf", b"%PDF-1.4 garbage").json()["error"]["code"] == "corrupt_pdf"
    assert upload(user, "empty.pdf", b"").json()["error"]["code"] == "empty_file"
    assert upload(user, "fake.jpg", b"\xff\xd8\xff\xe0 not really a jpeg").json()["error"]["code"] == "corrupt_image"


def test_image_without_ocr_goes_to_manual_review(user):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 300), "white").save(buf, format="PNG")
    r = upload(user, "screenshot.png", buf.getvalue(), kind="upi_screenshot")
    doc = user.get(f"/documents/{r.json()['id']}").json()
    assert doc["status"] == "needs_review"
    assert doc["extraction"]["fields"] == {}  # nothing invented
    assert doc["extraction"]["validation"][0]["code"] == "ocr_unavailable"
    # the user enters the details manually and confirms it as a payment
    r = user.post(f"/documents/{doc['id']}/confirm", {"merchant_name": "ABC Restaurant", "occurred_on": "2026-10-18", "amount": "450.00", "doc_kind": "upi_screenshot", "payment_reference": "429112345678"})
    assert r.status_code == 200
    assert r.json()["transaction"]["sources"][0]["role"] == "payment"


def test_download_links_are_short_lived_and_scoped(client, user, other_user):
    r = upload(user, "abc.pdf", receipt_pdf(RESTAURANT_RECEIPT))
    doc_id = r.json()["id"]
    link = user.get(f"/documents/{doc_id}/download-link").json()["url"]
    got = client.get(link)
    assert got.status_code == 200 and got.content.startswith(b"%PDF")
    assert got.headers["cache-control"] == "private, no-store"
    assert client.get(link[:-3] + "AAA").status_code == 404  # tampered token
    assert other_user.get(f"/documents/{doc_id}/download-link").status_code == 404
    from app.core.security import sign_download

    expired = sign_download(doc_id, user.household_id, -1)
    assert client.get(f"/api/v1/files/{expired}").status_code == 404


def test_confirmed_document_cannot_be_deleted(user):
    r = upload(user, "abc.pdf", receipt_pdf(RESTAURANT_RECEIPT))
    doc_id = r.json()["id"]
    user.post(f"/documents/{doc_id}/confirm", {"merchant_name": "ABC Restaurant", "occurred_on": "2026-10-18", "amount": "450.00"})
    assert user.delete(f"/documents/{doc_id}").status_code == 409
    assert Decimal(user.dashboard()["gross_spending"]) == Decimal("450.00")

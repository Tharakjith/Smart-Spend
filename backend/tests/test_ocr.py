"""OCR: line reconstruction (including tilted photos), OCR-tolerant parsing, and image bills end to end."""
import io
import math
from pathlib import Path

import pytest

from app.modules.documents.ocr import boxes_to_text
from app.modules.documents.parser import parse_document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _box(x, y, w, h, text, tilt_deg=0.0):
    """An OCR box (4 corners) for text at (x, y), rotated by tilt around the origin."""
    t = math.tan(math.radians(tilt_deg))
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return [[[px, py + t * px] for px, py in pts], text, 0.99]


def test_boxes_are_grouped_into_lines_and_columns():
    boxes = [_box(400, 100, 80, 20, "320.00"), _box(10, 100, 150, 20, "Rice 5kg"), _box(10, 140, 120, 20, "Sub Total"), _box(400, 141, 80, 20, "600.00")]
    assert boxes_to_text(boxes) == "Rice 5kg    320.00\nSub Total    600.00"


def test_tilted_photo_keeps_labels_with_their_values():
    # At 3° a value 600px to the right sits ~31px lower: more than a line height. Without tilt correction
    # "Sub Total" would pair with the discount's amount.
    rows = [("Sub Total", "600.00"), ("Discount", "20.00"), ("Grand Total", "595.00")]
    boxes = []
    for i, (label, value) in enumerate(rows):
        y = 100 + i * 30
        boxes += [_box(10, y, 160, 22, label, tilt_deg=3), _box(600, y, 90, 22, value, tilt_deg=3)]
    assert boxes_to_text(boxes).splitlines() == ["Sub Total    600.00", "Discount    20.00", "Grand Total    595.00"]


def test_parser_tolerates_typical_ocr_artefacts():
    text = "FRESH MART\nBi11No:FM-20481    Date:18/10/2026Time:19:42\nItem A    100.00\nSub Total    100.00\nCGST2.5%    2.50\nSGST2.5%    2.50\nGrand Total    Rs.105.00"
    f = parse_document(text)["fields"]
    assert f["invoice_number"]["value"] == "FM-20481"
    assert f["date"]["value"] == "2026-10-18" and f["time"]["value"] == "19:42:00"
    assert f["tax"]["value"] == "5.00" and f["total"]["value"] == "105.00"


def test_upi_amount_read_as_rs():
    f = parse_document("Payment successful\nRs 450\nPaid to\nABC Restaurant\n18 Oct2026,9:07PM\nUPItransaction ID: 429112345678")["fields"]
    assert f["total"]["value"] == "450" and f["date"]["value"] == "2026-10-18" and f["time"]["value"] == "21:07:00"
    assert f["payment_reference"]["value"] == "429112345678"


rapidocr = pytest.importorskip("rapidocr_onnxruntime", reason="RapidOCR not installed")


@pytest.fixture
def with_rapidocr(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ocr_provider", "rapidocr")


def test_image_bill_end_to_end(user, with_rapidocr):
    import pymupdf
    from PIL import Image

    # A phone-style photo of a printed receipt: rendered, tilted 2°, downscaled, JPEG-compressed.
    pix = pymupdf.open(FIXTURES / "receipt-freshmart-grocery.pdf")[0].get_pixmap(dpi=200)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB").rotate(2, expand=True, fillcolor="white")
    img = img.resize((img.width * 3 // 4, img.height * 3 // 4))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    r = user.post("/documents", files={"file": ("bill-photo.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 201, r.text
    doc = user.get(f"/documents/{r.json()['id']}").json()
    assert doc["extraction"]["method"] == "ocr"
    f = {k: v["value"] for k, v in doc["extraction"]["fields"].items()}
    assert (f["date"], f["total"], f["subtotal"], f["discount"], f["tax"], f["invoice_number"]) == ("2026-10-18", "595.00", "600.00", "20.00", "15.00", "FM-20481")
    assert len(doc["extraction"]["line_items"]) == 5
    assert not [i for i in doc["extraction"]["validation"] if i["level"] in ("error", "warning")]


def test_upi_screenshot_end_to_end(user, with_rapidocr):
    data = (FIXTURES / "upi-screenshot-abc-restaurant.png").read_bytes()
    r = user.post("/documents", files={"file": ("gpay.png", data, "image/png")})
    doc = user.get(f"/documents/{r.json()['id']}").json()
    assert doc["doc_kind"] == "upi_screenshot"
    f = {k: v["value"] for k, v in doc["extraction"]["fields"].items()}
    assert (f["merchant_name"], f["total"], f["payment_reference"]) == ("ABC Restaurant", "450", "429112345678")


def test_utility_bill_dates_and_misread_total_labels():
    # Shaped like an OCR'd electricity bill: the due-date label is lost, the bill date only appears in a
    # run-together print timestamp, and "Payable" / "Bill Amount" are misread.
    text = "\n".join(
        [
            "KSEB",
            "14-10-2024",
            "Disconn Dt    29-10-2024",
            "PrvRdD:02-08-2024",
            "alllAmount(Rs)    2208.00",
            "Payahie(Rs)    2210.00",
            "02/10/202410:13:57AM",
        ]
    )
    p = parse_document(text)
    f = p["fields"]
    assert f["date"]["value"] == "2024-10-02"  # earliest date not labelled due / disconnection / previous reading
    assert f["time"]["value"] == "10:13:57"
    assert f["total"]["value"] == "2210.00"  # "payable" preferred over "bill amount"
    assert "total_fuzzy_label" in {i["code"] for i in p["validation"]}


def test_labelled_bill_date_beats_due_date():
    from app.modules.documents.parser import parse_date

    assert parse_date("Due Date: 15/10/2026\nInvoice Date: 01/10/2026")[0].isoformat() == "2026-10-01"
    assert parse_date("Prev Rdg Date 23/10/2025\nCurr 22/12/2025\nDue Date 06/01/2026")[0].isoformat() == "2025-12-22"


def test_fuzzy_labels_do_not_accept_unrelated_words():
    text = "SHOP\nVariable charges    120.00\nBalance    80.00"
    assert parse_document(text)["fields"]["total"]["value"] is None

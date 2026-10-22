"""Writes sample documents to backend/fixtures/ for manual testing and demos.

python -m scripts.make_fixtures
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from tests.factories import BANK_CSV, GROCERY_RECEIPT, RESTAURANT_RECEIPT, UPI_SCREENSHOT_TEXT, receipt_pdf  # noqa: E402

OUT = ROOT / "fixtures"

PHARMACY_RECEIPT = [
    "APOLLO PHARMACY",
    "Kowdiar, Trivandrum",
    "Bill No: AP-55102   Date: 15/10/2026 11:20",
    "Paracetamol 500mg Tab   2   30.00    60.00",
    "Cetirizine 10mg Tab     1   45.00    45.00",
    "Hand Sanitizer 500ml    1  155.00   155.00",
    "Sub Total                           260.00",
    "Discount                             13.00",
    "Net Amount                     Rs. 247.00",
    "Paid by Card",
]

FUEL_RECEIPT = [
    "INDIAN OIL - SREE KRISHNA FUELS",
    "NH 66, Kazhakkoottam",
    "Receipt No: 004512   Date: 12-10-2026 08:41",
    "Product: Petrol   Rate: 106.80 / L",
    "Volume: 20.00 L",
    "Petrol 20 L x 106.80        2136.00",
    "Total                   ₹ 2136.00",
    "Mode: UPI   UPI Ref No: 428765432109",
]

ELECTRICITY_BILL = [
    "KERALA STATE ELECTRICITY BOARD",
    "Consumer No: 1145678901234",
    "Bill No: KSEB/OCT/88213   Bill Date: 05/10/2026",
    "Energy Charges                    1520.00",
    "Fixed Charges                      180.00",
    "Electricity Duty                   140.00",
    "Amount Payable                Rs. 1840.00",
    "Due Date: 20/10/2026",
]

# Ambiguous cases for the matcher: same merchant & amount on different days (must stay separate),
# a payment with a tip (needs confirmation), and a split payment covering two invoices.
AMBIGUOUS_CSV = """Date,Description,Amount,Reference
2026-10-10,UPI-FRESH MART-freshmart@ybl-HDFC0001234-429100000101-groceries,-450.00,429100000101
2026-10-14,UPI-FRESH MART-freshmart@ybl-HDFC0001234-429100000102-groceries,-450.00,429100000102
2026-10-16,UPI-CAFE MOCHA-cafemocha@okaxis-UTIB0000123-429100000103-coffee,-510.00,429100000103
2026-10-17,NEFT-OFFICE MART SUPPLIES-INV-1 INV-2,-1500.00,N2926101900001
2026-10-18,UPI REVERSAL-ZOMATO-zomato@hdfcbank-429100000104,750.00,429100000104
"""


def upi_screenshot_png() -> bytes:
    img = Image.new("RGB", (720, 1280), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
        small = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = small = ImageFont.load_default()
    y = 120
    for i, line in enumerate(UPI_SCREENSHOT_TEXT.splitlines()):
        d.text((60, y), line.replace("₹", "Rs "), fill="black", font=font if i < 2 else small)
        y += 80
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def card_statement_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    ws.append(["HDFC Bank Credit Card Statement - XXXX9912"])
    ws.append([])
    ws.append(["Transaction Date", "Description", "Amount", "Dr/Cr"])
    for row in [
        ("03/10/2026", "AMAZON PAY INDIA PVT LTD", "1,299.00", "DR"),
        ("04/10/2026", "NETFLIX.COM", "649.00", "DR"),
        ("09/10/2026", "REFUND AMAZON PAY INDIA", "299.00", "CR"),
        ("21/10/2026", "PAYMENT RECEIVED - THANK YOU", "12,000.00", "CR"),
    ]:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    files = {
        "receipt-freshmart-grocery.pdf": receipt_pdf(GROCERY_RECEIPT),
        "receipt-abc-restaurant.pdf": receipt_pdf(RESTAURANT_RECEIPT),
        "receipt-apollo-pharmacy.pdf": receipt_pdf(PHARMACY_RECEIPT),
        "receipt-indian-oil-fuel.pdf": receipt_pdf(FUEL_RECEIPT),
        "bill-kseb-electricity.pdf": receipt_pdf(ELECTRICITY_BILL),
        "upi-screenshot-abc-restaurant.png": upi_screenshot_png(),
        "statement-bank-xyz.csv": BANK_CSV.encode(),
        "statement-ambiguous-matches.csv": AMBIGUOUS_CSV.encode(),
        "statement-credit-card.xlsx": card_statement_xlsx(),
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"wrote fixtures/{name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()

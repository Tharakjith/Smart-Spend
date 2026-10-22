"""Categorisation across every category, from the inputs people actually have: bill text, UPI narrations,
card statement descriptors, line items. Each case names the evidence and the expected category; tricky
negatives check that misleading words don't win."""
import pytest

from app.modules.categories.classifier import classify
from app.modules.categories.defaults import DEFAULT_CATEGORIES, ITEM_KEYWORDS

EXPENSE_TOPS = {n for n, (kind, *_rest) in DEFAULT_CATEGORIES.items() if kind == "expense"}
INCOME_TOPS = {n for n, (kind, *_rest) in DEFAULT_CATEGORIES.items() if kind == "income"}
ITEM_TERMS: dict = {}
for term, path in ITEM_KEYWORDS.items():
    ITEM_TERMS.setdefault(path, {})[term] = 2.0

WATER_BILL = "KERALAWATER CUSTOMER 1916 Consumer id 2221303515 Meter No 608466 Reading Details ConsKL Water Charge 142 Sewerage Charge Meter Rent 4 Payable Amt Rs 303"
KSEB_BILL = "KSEB 1912 CUSTOMER CARE Demand/Disconnection Notice Supply Code 2014 Conn Id 4418064 KWH 9698 9348 350 Fuel Surcharge 66.50 Fixed Charge 360 Meter Rent 30 Payable 2210"
BESCOM_BILL = "BANGALORE ELECTRICITY SUPPLY COMPANY BESCOM RR No Units consumed 212 Energy Charges 1310 Fixed charges 220 Net amount 1530"
LPG_BILL = "INDANE Cash Memo Consumer No 123456 Refill 14.2 kg cylinder LPG Amount 903.00"
BROADBAND_BILL = "ACT Fibernet Invoice Plan ACT Blaze 150 Mbps Broadband Rental 999 GST 18% Total 1178.82"
RESTAURANT_BILL = "Hotel Aryaas Vegetarian Restaurant Table No 7 Masala Dosa 2 140.00 Filter Coffee 2 60.00 Mineral Water 1 20.00 Total 220.00"
GROCERY_BILL = "FRESH MART SUPERMARKET Rice Ponni 5kg 320.00 Milk 1L 60.00 Bisleri Packaged Drinking Water 1L 20.00 Grand Total 400.00"
PHARMACY_BILL = "APOLLO PHARMACY Paracetamol 500mg Tab Batch No A12 Exp Date 12/27 Cetirizine Tab Net Amount 247"
HOSPITAL_BILL = "KIMS HEALTH Hospital OPD Consultation Dr. Meera Nair General Medicine Consultation Fee 600"
LAB_BILL = "DDRC Agilus Diagnostics Laboratory Complete Blood Count Thyroid Profile Total 850"
FUEL_BILL = "INDIAN OIL - SREE KRISHNA FUELS Petrol 20 L x 106.80 2136.00"

CASES = [
    # ---- utilities: the user's own bills and their peers
    dict(merchant="KERALAWATER", document=WATER_BILL, expect="Electricity and Utilities/Water"),
    dict(merchant="Kerala Water Authority", expect="Electricity and Utilities/Water"),
    dict(merchant="KSEB", document=KSEB_BILL, expect="Electricity and Utilities/Electricity"),
    dict(merchant="BANGALORE ELECTRICITY SUPPLY", document=BESCOM_BILL, expect="Electricity and Utilities/Electricity"),
    dict(description="UPI/DR/429112345678/KSEB LTD/SBIN/kseb@sbi/Electricity bill", expect="Electricity and Utilities/Electricity"),
    dict(description="BBPS-TATA POWER-DDL-BILLPAY", expect="Electricity and Utilities/Electricity"),
    dict(description="UPI/DR/4291/DELHI JAL BOARD/HDFC/djb@hdfc/water", expect="Electricity and Utilities/Water"),
    dict(description="BWSSB WATER BILL PAYMENT", expect="Electricity and Utilities/Water"),
    dict(merchant="Indane Gas Agency", document=LPG_BILL, expect="Electricity and Utilities/Gas"),
    dict(description="UPI-HP GAS-hpgas@icici-LPG booking", expect="Electricity and Utilities/Gas"),
    dict(description="IGL PNG BILL", expect="Electricity and Utilities/Gas"),
    dict(merchant="ACT Fibernet", document=BROADBAND_BILL, expect="Electricity and Utilities/Broadband"),
    dict(description="UPI/DR/4291/JIOFIBER/YESB/jio@ybl", expect="Electricity and Utilities/Broadband"),
    dict(description="ASIANET BROADBAND RENEWAL", expect="Electricity and Utilities/Broadband"),
    dict(description="TATA PLAY DTH RECHARGE", expect="Electricity and Utilities/Broadband"),
    dict(description="JIO PREPAID RECHARGE 299", expect="Electricity and Utilities/Mobile"),
    dict(description="AIRTEL POSTPAID BILL", expect="Electricity and Utilities/Mobile"),
    # ---- food
    dict(merchant="Hotel Aryaas", document=RESTAURANT_BILL, expect="Food and Dining/Restaurants"),
    dict(merchant="Paradise Biryani", expect="Food and Dining/Restaurants"),
    dict(description="POS 4XXX1234 DOMINOS PIZZA", expect="Food and Dining/Restaurants"),
    dict(merchant="ABC Restaurant", expect="Food and Dining/Restaurants"),
    dict(merchant="Chaayos", expect="Food and Dining/Cafes & Snacks"),
    dict(merchant="Iyengar Bakery", expect="Food and Dining/Cafes & Snacks"),
    dict(description="UPI/DR/4291/SWIGGY/AXIS/swiggy@axisbank", expect="Food and Dining/Food Delivery"),
    dict(description="ZOMATO ORDER 1234", expect="Food and Dining/Food Delivery"),
    # ---- groceries
    dict(merchant="FRESH MART SUPERMARKET", document=GROCERY_BILL, items=["Rice Ponni 5kg", "Milk 1L", "Bisleri Packaged Drinking Water 1L"], expect="Groceries"),
    dict(description="POS 4XXX DMART AVENUE TVM", expect="Groceries"),
    dict(description="UPI/DR/4291/BLINKIT/ICIC/blinkit@icici", expect="Groceries"),
    dict(merchant="Sree Murugan Provision Store", expect="Groceries"),
    dict(merchant="Corner Store", items=["Atta 5kg", "Toor Dal 1kg", "Sugar 1kg"], expect="Groceries/Staples"),
    # ---- housing
    dict(description="NEFT-HOUSE RENT OCT-MR NAIR", expect="Housing and Rent/Rent"),
    dict(description="UPI/DR/4291/SKY APARTMENTS SOCIETY MAINTENANCE", expect="Housing and Rent/Maintenance & Repairs"),
    dict(merchant="Urban Company", description="AC service", expect="Housing and Rent/Maintenance & Repairs"),
    dict(merchant="IKEA", expect="Housing and Rent/Furnishing"),
    # ---- transport
    dict(merchant="Indian Oil", document=FUEL_BILL, expect="Transportation and Fuel/Fuel"),
    dict(description="POS 4XXX NAYARA ENERGY PETROL PUMP", expect="Transportation and Fuel/Fuel"),
    dict(description="UPI/DR/4291/UBER INDIA/HDFC/uber@hdfc", expect="Transportation and Fuel/Cab & Auto"),
    dict(description="RAPIDO BIKE TAXI", expect="Transportation and Fuel/Cab & Auto"),
    dict(description="KSRTC ONLINE BUS TICKET", expect="Transportation and Fuel/Public Transport"),
    dict(description="FASTAG RECHARGE NHAI TOLL", expect="Transportation and Fuel/Parking & Tolls"),
    dict(merchant="Popular Motors", description="car service and tyres", expect="Transportation and Fuel/Vehicle Service"),
    # ---- shopping
    dict(description="AMAZON PAY INDIA PVT LTD", expect="Shopping/Online Shopping"),
    dict(description="FLIPKART INTERNET PVT LTD", expect="Shopping/Online Shopping"),
    dict(merchant="Myntra", expect="Shopping/Clothing"),
    dict(merchant="Kalyan Silks", expect="Shopping/Clothing"),
    dict(merchant="Croma", expect="Shopping/Electronics"),
    dict(merchant="Reliance Digital", expect="Shopping/Electronics"),
    # ---- health
    dict(merchant="APOLLO PHARMACY", document=PHARMACY_BILL, expect="Healthcare and Medicines/Medicines"),
    dict(merchant="Sree Medicals", expect="Healthcare and Medicines/Medicines"),
    dict(merchant="KIMS Health", document=HOSPITAL_BILL, expect="Healthcare and Medicines/Doctor & Hospital"),
    dict(merchant="Smile Dental Clinic", expect="Healthcare and Medicines/Doctor & Hospital"),
    dict(merchant="DDRC Agilus", document=LAB_BILL, expect="Healthcare and Medicines/Diagnostics"),
    # ---- education, travel, entertainment, subscriptions
    dict(description="NEFT-ST THOMAS SCHOOL TUITION FEE", expect="Education/Tuition & Fees"),
    dict(merchant="DC Books", expect="Education/Books & Courses"),
    dict(description="IRCTC E TICKET PNR 4521", expect="Travel and Accommodation/Flights & Trains"),
    dict(description="INDIGO AIRLINES 6E 123", expect="Travel and Accommodation/Flights & Trains"),
    dict(merchant="OYO Rooms", expect="Travel and Accommodation/Hotels"),
    dict(description="MAKEMYTRIP INDIA", expect="Travel and Accommodation"),
    dict(description="BOOKMYSHOW 4 TICKETS", expect="Entertainment and Gaming/Movies & Events"),
    dict(merchant="PVR Cinemas", expect="Entertainment and Gaming/Movies & Events"),
    dict(description="NETFLIX.COM", expect="Entertainment and Gaming/Streaming"),
    dict(description="SPOTIFY INDIA", expect="Entertainment and Gaming/Streaming"),
    dict(description="STEAM PURCHASE", expect="Entertainment and Gaming/Gaming"),
    dict(description="GOOGLE ONE STORAGE", expect="Subscriptions/Software & Apps"),
    # ---- personal care, insurance, finance, gifts, taxes, work
    dict(merchant="Naturals Salon", expect="Personal Care/Salon & Grooming"),
    dict(merchant="Cult.fit", description="gym membership", expect="Personal Care/Fitness"),
    dict(description="LIC OF INDIA PREMIUM", expect="Insurance/Life Insurance"),
    dict(description="STAR HEALTH INSURANCE RENEWAL", expect="Insurance/Health Insurance"),
    dict(description="HDFC ERGO MOTOR INSURANCE", expect="Insurance/Vehicle Insurance"),
    dict(description="ANNUAL FEE CREDIT CARD", expect="Loan Interest and Financial Charges/Bank Charges"),
    dict(description="LATE PAYMENT FEE", expect="Loan Interest and Financial Charges/Late Fees"),
    dict(description="SREE PADMANABHA SWAMY TEMPLE DONATION", expect="Gifts and Donations/Donations & Charity"),
    dict(merchant="Ferns N Petals", expect="Gifts and Donations/Gifts"),
    dict(description="CORPORATION OF TRIVANDRUM PROPERTY TAX", expect="Taxes/Property Tax"),
    dict(description="ADVANCE TAX CHALLAN 280", expect="Taxes/Income Tax"),
    dict(merchant="Ganesh Xerox", expect="Work and Business Expenses/Office Supplies"),
    # ---- negatives: nothing convincing -> leave uncategorised rather than guess
    dict(merchant="XYZ Traders", expect=None),
    dict(description="UPI/DR/4291/RAHUL K/YESB/rahul@ybl/dinner share", expect=None),
]


def _run(case, kind="expense"):
    return classify(
        merchant=case.get("merchant", ""),
        description=case.get("description", ""),
        items=case.get("items", []),
        document_text=case.get("document", ""),
        allowed_paths=EXPENSE_TOPS if kind == "expense" else INCOME_TOPS,
        item_terms=ITEM_TERMS,
    )


@pytest.mark.parametrize("case", CASES, ids=[c.get("merchant") or c.get("description") for c in CASES])
def test_category(case):
    d = _run(case)
    assert d.path == case["expect"], f"got {d.path} (scores {d.scores}, reasons {d.reasons})"
    if case["expect"]:
        assert d.reasons, "a decision always carries its evidence"


def test_misleading_words_do_not_win():
    # A restaurant bill mentions mineral water; an electricity bill mentions fuel surcharge and meter rent.
    assert _run(dict(merchant="Hotel Aryaas", document=RESTAURANT_BILL)).path == "Food and Dining/Restaurants"
    d = _run(dict(merchant="KSEB", document=KSEB_BILL))
    assert d.scores.get("Transportation and Fuel", 0) == 0 and d.scores.get("Housing and Rent", 0) == 0


def test_income():
    assert _run(dict(description="NEFT-SALARY ACME CORP OCT"), kind="income").path == "Salary"
    assert _run(dict(description="SB INTEREST CREDIT"), kind="income").path == "Interest and Dividends"


def test_accuracy_summary():
    hits = sum(1 for c in CASES if _run(c).path == c["expect"])
    assert hits == len(CASES), f"{hits}/{len(CASES)}"


# ---- through the API: bill text is used, the reason is stored, custom categories and learning work
def test_bill_text_drives_category_and_reason_is_shown(user):
    from tests.factories import receipt_pdf

    pdf = receipt_pdf(["KERALA WATER AUTHORITY", "Bill No & Date 183049449 - 22/12/2025", "Consumer id 2221303515", "Water Charge 142.00", "Sewerage Charge 0.00", "Meter Rent 4.00", "Payable Amt Rs. 303.00"])
    doc = user.post("/documents", files={"file": ("kwa.pdf", pdf, "application/pdf")}).json()
    detail = user.get(f"/documents/{doc['id']}").json()
    cats = {c["id"]: c["name"] for c in user.get("/categories").json()}
    assert cats[detail["extraction"]["suggested_category_id"]] == "Water"
    assert any("water" in r for r in detail["extraction"]["category_reasons"])
    tx = user.post(f"/documents/{doc['id']}/confirm", {"merchant_name": "KERALA WATER AUTHORITY", "occurred_on": "2025-12-22", "amount": "303.00"}).json()["transaction"]
    assert tx["category_name"] == "Water" and tx["category_reasons"]


def test_custom_category_is_recognised(user):
    parent = next(c for c in user.get("/categories").json() if c["name"] == "Family Support")
    user.post("/categories", {"name": "Pet Care", "parent_id": parent["id"]})
    t = user.payment("1200.00", "Happy Paws", description="Pet care grooming and vaccines")
    assert t["category_name"] == "Pet Care"


def test_a_correction_teaches_the_next_bill_from_that_merchant(user):
    cats = {c["name"]: c["id"] for c in user.get("/categories").json()}
    t = user.payment("450.00", "Mystery Vendor 42")
    assert t["category_name"] == "Other and Uncategorized"
    user.patch(f"/transactions/{t['id']}", {"category_id": cats["Water"]})
    assert user.payment("460.00", "Mystery Vendor 42")["category_name"] == "Water"


def test_recategorize_upgrades_only_automatic_categories(user):
    cats = {c["name"]: c["id"] for c in user.get("/categories").json()}
    auto = user.payment("303.00", "Unknown Utility Co")
    mine = user.payment("500.00", "Another Unknown", category_id=cats["Gifts"])
    # Simulate a category chosen by an older, weaker version of the rules.
    from sqlalchemy import update

    from app.core.db import SessionLocal
    from app.models import CanonicalTransaction

    with SessionLocal() as db:
        db.execute(update(CanonicalTransaction).where(CanonicalTransaction.id == auto["id"]).values(description="KWA water charge bill", category_source="uncategorized"))
        db.commit()
    r = user.post("/transactions/recategorize", {}).json()
    assert [c["to"] for c in r["changed"] if c["id"] == auto["id"]] == ["Water"]
    assert user.txn(mine["id"])["category_name"] == "Gifts"

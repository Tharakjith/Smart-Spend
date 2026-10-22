"""Seeds an explicitly flagged DEMO household. Refuses to run unless DEMO_MODE=true and ENVIRONMENT != production.

Login: demo@example.com / DemoPassw0rd!   (idempotent: does nothing if the demo user exists)
All data goes through the public API so it is validated, categorised and reconciled exactly like real data.
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "DemoPassw0rd!"


def main() -> None:
    if os.environ.get("DEMO_MODE", "").lower() != "true" or os.environ.get("ENVIRONMENT") == "production":
        print("Refusing to seed demo data: set DEMO_MODE=true in a non-production environment.")
        return
    os.environ.setdefault("REQUIRE_EMAIL_VERIFICATION", "false")
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.main import app
    from app.models import Household, HouseholdMember, User
    from tests.factories import GROCERY_RECEIPT, RESTAURANT_RECEIPT, receipt_pdf

    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User).where(User.email == DEMO_EMAIL)):
            print("Demo data already present.")
            return

    c = TestClient(app)
    r = c.post("/api/v1/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, "full_name": "Demo User", "household_name": "Demo Workspace (sample data)"})
    r.raise_for_status()
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == DEMO_EMAIL)).one()
        if u.email_verified_at is None:
            from app.core.db import utcnow

            u.email_verified_at = utcnow()
        hid = db.scalars(select(HouseholdMember.household_id).where(HouseholdMember.user_id == u.id)).one()
        db.get(Household, hid).is_demo = True
        db.commit()
    tok = c.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}", "X-Household-ID": str(hid)}

    def post(path, body=None, **kw):
        res = c.post(f"/api/v1{path}", json=body, headers=H, **kw)
        if res.status_code >= 400:
            raise RuntimeError(f"{path}: {res.status_code} {res.text}")
        return res.json()

    today = date.today()
    first = today.replace(day=1)
    m0 = first
    m1 = (m0 - timedelta(days=1)).replace(day=1)
    m2 = (m1 - timedelta(days=1)).replace(day=1)

    bank = post("/accounts", {"name": "SBI Savings", "type": "bank", "opening_balance": "85000.00", "opening_balance_date": m2.isoformat(), "institution": "SBI", "masked_number": "4821", "upi_handle": "demo@oksbi"})
    card = post(
        "/accounts",
        {"name": "HDFC Credit Card", "type": "credit_card", "institution": "HDFC", "masked_number": "9912", "credit_limit": "200000", "statement_day": 15, "due_day": 5, "opening_balance_date": m2.isoformat()},
    )
    cats = {x["name"]: x["id"] for x in c.get("/api/v1/categories", headers=H).json()}

    def tx(**kw):
        body = {"type": "expense", "currency": "INR", **kw}
        return post("/transactions", body)

    for m in (m2, m1, m0):
        if m > today:
            continue
        d = lambda day: min(m.replace(day=day), today).isoformat()  # noqa: E731
        tx(type="income", amount="92000.00", occurred_on=d(1), description="Salary - Acme Corp", account_id=bank["id"], category_id=cats["Salary"])
        tx(amount="22000.00", occurred_on=d(2), merchant_name="Landlord - Mr. Nair", description="House rent", payment_method="bank_transfer", account_id=bank["id"], category_id=cats["Rent"], is_recurring=True)
        tx(amount="1840.00", occurred_on=d(6), merchant_name="KSEB", description="Electricity bill", payment_method="upi", account_id=bank["id"])
        tx(amount="799.00", occurred_on=d(8), merchant_name="ACT Fibernet", description="Broadband", payment_method="upi", account_id=bank["id"], is_recurring=True)
        tx(amount="649.00", occurred_on=d(12), merchant_name="Netflix", payment_method="credit_card", account_id=card["id"])
        tx(amount="2450.00", occurred_on=d(14), merchant_name="Indian Oil", description="Petrol", payment_method="debit_card", account_id=bank["id"])
        tx(amount="380.00", occurred_on=d(16), merchant_name="Swiggy", payment_method="upi", account_id=bank["id"])
        tx(amount="1260.00", occurred_on=d(19), merchant_name="Apollo Pharmacy", payment_method="upi", account_id=bank["id"])

    # A receipt uploaded and confirmed, and its UPI payment recorded separately -> suggested match to review.
    doc = c.post("/api/v1/documents", headers=H, files={"file": ("freshmart-receipt.pdf", receipt_pdf(GROCERY_RECEIPT), "application/pdf")}).json()
    f = c.get(f"/api/v1/documents/{doc['id']}", headers=H).json()["extraction"]
    items = [{k: i[k] for k in ("name", "quantity", "unit", "unit_price", "line_total")} for i in f["line_items"]]
    receipt_day = min(today, m0.replace(day=min(18, today.day)))
    post(f"/documents/{doc['id']}/confirm", {"merchant_name": "Fresh Mart Supermarket", "occurred_on": receipt_day.isoformat(), "amount": "595.00", "doc_kind": "invoice", "invoice_number": "FM-20481", "line_items": items})
    tx(amount="595.00", occurred_on=receipt_day.isoformat(), merchant_name="FRESHMART TRIVANDRUM", payment_method="upi", account_id=bank["id"], description="UPI payment")

    # Restaurant bill whose UPI payment includes a ₹10 tip -> medium-confidence suggestion.
    doc2 = c.post("/api/v1/documents", headers=H, files={"file": ("abc-restaurant.pdf", receipt_pdf(RESTAURANT_RECEIPT), "application/pdf")}).json()
    post(f"/documents/{doc2['id']}/confirm", {"merchant_name": "ABC Restaurant", "occurred_on": receipt_day.isoformat(), "amount": "450.00", "doc_kind": "receipt"})
    tx(amount="460.00", occurred_on=receipt_day.isoformat(), merchant_name="ABC Restaurant", payment_method="upi", account_id=bank["id"])

    # People: a split dinner, a loan with a repayment.
    anu = post("/counterparties", {"name": "Anu", "upi_id": "anu@okhdfc"})
    rahul = post("/counterparties", {"name": "Rahul", "upi_id": "rahul@ybl"})
    post("/shared-expenses", {"description": "Team dinner at Spice Route", "total_amount": "1500.00", "occurred_on": m1.replace(day=20).isoformat(), "merchant_name": "Spice Route", "participants": [{"counterparty_id": None}, {"counterparty_id": anu["id"]}, {"counterparty_id": rahul["id"]}]})
    loan = post("/loans", {"counterparty_id": rahul["id"], "direction": "given", "principal": "10000.00", "start_date": m2.replace(day=10).isoformat(), "due_date": (today + timedelta(days=60)).isoformat()})
    post(f"/loans/{loan['id']}/repayments", {"paid_on": m1.replace(day=10).isoformat(), "principal_amount": "4000.00"})

    # Credit card: a few more card purchases, then the latest bill (left unpaid so its reminder shows).
    stmt_date = m0.replace(day=15) if today.day >= 15 else m1.replace(day=15)
    for days_before, amount, merchant in ((12, "4999.00", "Croma"), (6, "1299.00", "Amazon"), (2, "2150.00", "Decathlon")):
        tx(amount=amount, occurred_on=(stmt_date - timedelta(days=days_before)).isoformat(), merchant_name=merchant, payment_method="credit_card", account_id=card["id"])
    preview = c.get(f"/api/v1/credit-cards/{card['id']}/statement-preview?statement_date={stmt_date.isoformat()}", headers=H).json()
    total = Decimal(preview["computed_total_due"])
    post(
        f"/credit-cards/{card['id']}/statements",
        {
            "statement_date": stmt_date.isoformat(),
            "due_date": preview["suggested_due_date"],
            "total_due": format(total, "f"),
            "minimum_due": format((total * Decimal("0.05")).quantize(Decimal("0.01")), "f"),  # typical 5% minimum for the demo
        },
    )

    # Budgets, a goal and recurring bills.
    post("/budgets", {"name": "Monthly spending", "period": "monthly", "amount": "45000"})
    post("/budgets", {"name": "Eating out", "period": "monthly", "category_id": cats["Food and Dining"], "amount": "3000"})
    post("/savings-goals", {"name": "Emergency fund", "target_amount": "300000", "saved_amount": "120000", "target_date": (today + timedelta(days=365)).isoformat()})
    post("/recurring", {"name": "House rent", "amount": "22000", "frequency": "monthly", "next_due_date": (m0.replace(day=2) if today.day < 2 else (m0 + timedelta(days=32)).replace(day=2)).isoformat(), "category_id": cats["Rent"]})
    post("/recurring", {"name": "Netflix", "amount": "649", "frequency": "monthly", "next_due_date": (today + timedelta(days=3)).isoformat(), "is_subscription": True})
    c.post("/api/v1/notifications/run-checks", headers=H)
    print(f"Demo data created. Sign in as {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()

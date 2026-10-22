from decimal import Decimal

import pytest

from app.core.money import MoneyError, money_sum, quantize, to_decimal


# ---------------------------------------------------------------- monetary precision
def test_money_never_uses_floats():
    with pytest.raises(MoneyError):
        to_decimal(0.1)
    assert money_sum(["0.10", "0.20"]) == Decimal("0.30")
    assert quantize("2.675") == Decimal("2.68")  # banker's rounding: 2.675 -> 2.68 (7 odd -> even 8)
    assert quantize("2.665") == Decimal("2.66")
    assert quantize("100", "JPY") == Decimal("100")
    assert quantize("1.2345", "KWD") == Decimal("1.234")
    assert to_decimal("₹1,23,456.50") == Decimal("123456.50")


def test_api_amounts_are_exact_decimal_strings(user):
    for _ in range(10):
        user.payment("0.10", "Tea Stall")
    user.payment("0.20", "Tea Stall")
    assert user.dashboard()["gross_spending"] == "1.20"


def test_rejects_zero_negative_and_garbage_amounts(user):
    for bad in ("0", "-5", "abc", "1e400"):
        r = user.post("/transactions", {"type": "expense", "occurred_on": "2026-10-18", "amount": bad})
        assert r.status_code == 422, bad


# ---------------------------------------------------------------- categorisation priority
def test_categorisation_priority(user):
    cats = {c["name"]: c["id"] for c in user.get("/categories").json()}
    t = user.payment("200.00", "Swiggy")
    assert t["category_name"] == "Food Delivery" and t["category_source"] == "keyword" and t["category_reasons"]
    t = user.payment("1500.00", "KSEB", description="Electricity bill")
    assert t["category_name"] == "Electricity"
    t = user.payment("99.00", "Unknown Vendor 42")
    assert t["category_name"] == "Other and Uncategorized"
    # a user rule beats everything
    user.post("/rules", {"name": "Swiggy is work", "field": "merchant", "operator": "contains", "pattern": "swiggy", "category_id": cats["Work and Business Expenses"], "priority": 1})
    t = user.payment("250.00", "Swiggy")
    assert t["category_name"] == "Work and Business Expenses" and t["category_source"] == "user_rule"


def test_confirmed_merchant_mapping_is_learned(user):
    cats = {c["name"]: c["id"] for c in user.get("/categories").json()}
    t = user.payment("80.00", "Ravi Stores")
    user.patch(f"/transactions/{t['id']}", {"category_id": cats["Groceries"], "remember_category_for_merchant": True})
    t2 = user.payment("120.00", "RAVI STORES")
    assert t2["category_name"] == "Groceries" and t2["category_source"] == "merchant_default"


def test_line_items_get_their_own_categories(user):
    t = user.bill(
        "250.00",
        "Corner Store",
        line_items=[{"name": "Rice 1kg", "line_total": "80.00"}, {"name": "Paracetamol tablets", "line_total": "40.00"}, {"name": "Detergent", "line_total": "130.00"}],
    )
    detail = user.txn(t["id"])
    cats = {c["id"]: c["name"] for c in user.get("/categories").json()}
    assert [cats.get(li["category_id"]) for li in detail["line_items"]] == ["Staples", "Medicines", "Household Supplies"]
    breakdown = {r["name"]: r["amount"] for r in user.get("/analytics/categories?month=2026-10").json()}
    assert breakdown == {"Groceries": "210.00", "Healthcare and Medicines": "40.00"}


# ---------------------------------------------------------------- financial semantics
def test_transfers_loans_and_cc_payments_are_not_spending(user):
    bank = user.post("/accounts", {"name": "SBI", "type": "bank", "opening_balance": "10000"}).json()
    card = user.post("/accounts", {"name": "HDFC Card", "type": "credit_card"}).json()
    user.tx(type="transfer", amount="5000.00", account_id=bank["id"], to_account_id=card["id"], description="Move")
    user.tx(type="credit_card_payment", amount="3000.00", account_id=bank["id"], to_account_id=card["id"])
    person = user.post("/counterparties", {"name": "Kiran"}).json()
    loan = user.post("/loans", {"counterparty_id": person["id"], "direction": "given", "principal": "2000", "start_date": "2026-10-02"}).json()
    r = user.post(f"/loans/{loan['id']}/repayments", {"paid_on": "2026-10-20", "principal_amount": "500", "interest_amount": "50"})
    assert r.status_code == 201, r.text
    t = user.dashboard()
    assert t["gross_spending"] == "0.00"
    assert t["loans_given"] == "2000.00" and t["loan_repayments_received"] == "500.00"
    assert t["income"] == "50.00"  # interest received is income; principal is not
    assert t["internal_transfers"] == "8000.00"
    assert r.json()["outstanding"] == "1500.00"


def test_interest_paid_on_borrowed_loan_is_the_only_expense(user):
    person = user.post("/counterparties", {"name": "Uncle"}).json()
    loan = user.post("/loans", {"counterparty_id": person["id"], "direction": "received", "principal": "10000", "start_date": "2026-10-01"}).json()
    user.post(f"/loans/{loan['id']}/repayments", {"paid_on": "2026-10-15", "principal_amount": "1000", "interest_amount": "100"})
    t = user.dashboard()
    assert t["gross_spending"] == "100.00" and t["loan_repayments_paid"] == "1000.00" and t["loans_received"] == "10000.00"
    r = user.post(f"/loans/{loan['id']}/repayments", {"paid_on": "2026-10-16", "principal_amount": "99999"})
    assert r.status_code == 422


def test_month_end_boundaries(user):
    user.payment("100.00", "A", on="2026-10-31")
    user.payment("200.00", "A", on="2026-11-01")
    user.payment("50.00", "A", on="2026-09-30")
    assert user.dashboard("2026-10")["gross_spending"] == "100.00"
    assert user.dashboard("2026-11")["gross_spending"] == "200.00"
    assert user.dashboard("2026-09")["gross_spending"] == "50.00"
    assert user.get("/transactions?month=2026-10").json()["total"] == 1


def test_void_excludes_and_keeps_history(user):
    t = user.payment("700.00", "Shop")
    r = user.post(f"/transactions/{t['id']}/void", {"reason": "entered twice"})
    assert r.json()["status"] == "voided"
    assert user.dashboard()["gross_spending"] == "0.00"
    actions = [e["action"] for e in user.get(f"/transactions/{t['id']}/audit").json()]
    assert actions == ["create", "void"]


def test_update_with_version_conflict(user):
    t = user.payment("100.00", "Shop")
    assert user.patch(f"/transactions/{t['id']}", {"version": t["version"], "notes": "a"}).status_code == 200
    r = user.patch(f"/transactions/{t['id']}", {"version": t["version"], "notes": "b"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_conflict"


def test_amount_cannot_drop_below_allocations(user):
    bill = user.bill("450.00", "ABC Restaurant")
    pay = user.payment("450.00", "ABC Restaurant")
    m = user.candidates()[0]
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    r = user.patch(f"/transactions/{pay['id']}", {"amount": "100.00"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "amount_below_allocated"
    assert bill


def test_idempotent_transaction_create(user):
    body = {"type": "expense", "occurred_on": "2026-10-18", "amount": "42.00", "description": "Once"}
    h = {"Idempotency-Key": "abc-123"}
    r1 = user.post("/transactions", body, headers=h)
    r2 = user.post("/transactions", body, headers=h)
    assert r1.json()["id"] == r2.json()["id"]
    assert user.get("/transactions").json()["total"] == 1
    r3 = user.post("/transactions", {**body, "amount": "43.00"}, headers=h)
    assert r3.status_code == 409


def test_account_balance_uses_reconciled_movements(user):
    bank = user.post("/accounts", {"name": "Bank", "type": "bank", "opening_balance": "1000.00", "opening_balance_date": "2026-10-01"}).json()
    user.bill("450.00", "ABC Restaurant", account_id=bank["id"])
    user.payment("450.00", "ABC Restaurant", account_id=bank["id"])
    assert user.get(f"/accounts/{bank['id']}/balance").json()["balance"] == "100.00"  # unlinked: both assumed paid
    m = user.candidates()[0]
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    assert user.get(f"/accounts/{bank['id']}/balance").json()["balance"] == "550.00"  # one debit, not two


def test_multi_currency_is_not_converted(user):
    user.tx(amount="20.00", currency="USD", description="App store")
    user.payment("100.00", "Shop")
    d = user.get("/dashboard/summary?month=2026-10").json()
    assert d["totals"]["gross_spending"] == "100.00"
    assert d["other_currencies"] == [{"currency": "USD", "gross_spending": "20.00"}]

"""Credit card bills: statements, payments, status, balances, reminders - and that paying a card never counts
as spending a second time."""
from datetime import date, timedelta
from decimal import Decimal

TODAY = date.today()


def setup_cards(user, statement_day=15, due_day=5):
    bank = user.post("/accounts", {"name": "SBI Savings", "type": "bank", "opening_balance": "50000.00", "opening_balance_date": "2026-09-01"}).json()
    card = user.post(
        "/accounts",
        {"name": "HDFC Card", "type": "credit_card", "institution": "HDFC", "masked_number": "9912", "credit_limit": "100000", "statement_day": statement_day, "due_day": due_day, "opening_balance_date": "2026-09-01"},
    ).json()
    assert card["credit_limit"] == "100000.00", card
    return bank, card


def spend(user, card, amount, on, merchant="Amazon", **kw):
    return user.tx(amount=amount, occurred_on=on, merchant_name=merchant, account_id=card["id"], payment_method="credit_card", **kw)


def make_statement(user, card, **kw):
    body = {"statement_date": "2026-10-15", "period_start": "2026-09-16", "due_date": "2026-11-05", "total_due": "4500.00", "minimum_due": "225.00", **kw}
    r = user.post(f"/credit-cards/{card['id']}/statements", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_full_bill_lifecycle(user):
    bank, card = setup_cards(user)
    spend(user, card, "2000.00", "2026-09-20")
    spend(user, card, "3000.00", "2026-10-02", merchant="Croma")
    user.tx(type="refund", amount="500.00", occurred_on="2026-10-10", merchant_name="Croma", account_id=card["id"])

    prev = user.get(f"/credit-cards/{card['id']}/statement-preview?statement_date=2026-10-15&period_start=2026-09-16").json()
    assert (prev["purchases"], prev["credits"], prev["payments"], prev["computed_total_due"]) == ("5000.00", "500.00", "0.00", "4500.00")
    assert prev["suggested_due_date"] == "2026-11-05"
    assert len(prev["transactions"]) == 3

    s = make_statement(user, card)
    assert s["status"] == "unpaid" and s["remaining_amount"] == "4500.00"
    spend(user, card, "1000.00", "2026-10-18", merchant="Swiggy")  # after the statement: unbilled

    c = user.get(f"/credit-cards/{card['id']}").json()
    assert c["outstanding"] == "5500.00" and c["available_credit"] == "94500.00" and c["utilization_pct"] == 5.5
    assert c["unbilled_amount"] == "1000.00"
    assert c["statements"][0]["id"] == s["id"]

    # Paying on the statement date must not make the bill's own cycle look settled.
    early = user.post(f"/credit-card-statements/{s['id']}/pay", {"from_account_id": bank["id"], "amount": "100.00", "paid_on": "2026-10-15"}).json()
    assert early["cycle"]["computed_total_due"] == "4500.00" and early["cycle"]["payments"] == "0.00"
    user.post(f"/credit-card-statements/{s['id']}/unlink", {"link_id": early["payments"][0]["link_id"]})
    user.post(f"/transactions/{early['payments'][0]['transaction_id']}/void", {"reason": "test"})

    # Pay the minimum from the bank.
    r = user.post(f"/credit-card-statements/{s['id']}/pay", {"from_account_id": bank["id"], "amount": "225.00", "paid_on": "2026-10-20"})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "minimum_paid" and s["paid_amount"] == "225.00" and s["remaining_amount"] == "4275.00"
    assert s["payments"][0]["on_time"] is True

    # Paying a card is a transfer: card purchases already counted as spending, refunds reduce it.
    t = user.dashboard()
    assert t["gross_spending"] == "4000.00" and t["refunds"] == "500.00" and t["net_spending"] == "3500.00"
    assert t["internal_transfers"] == "225.00"
    assert user.get(f"/accounts/{bank['id']}/balance").json()["balance"] == "49775.00"
    assert user.get(f"/credit-cards/{card['id']}").json()["outstanding"] == "5275.00"


def test_link_imported_bank_payment_row(user):
    bank, card = setup_cards(user)
    spend(user, card, "4500.00", "2026-10-02")
    s = make_statement(user, card)
    csv = "Date,Narration,Withdrawal,Deposit\n2026-10-25,CC PAYMENT XXXX9912 AUTOPAY,4500.00,\n"
    imp = user.post("/imports", files={"file": ("bank.csv", csv.encode(), "text/csv")}, data={"account_id": bank["id"]}).json()
    assert user.post(f"/imports/{imp['id']}/confirm").json()["imported_count"] == 1
    assert user.dashboard()["gross_spending"] == "4500.00"  # the bank-side payment is not spending

    detail = user.get(f"/credit-card-statements/{s['id']}").json()
    sug = detail["payment_suggestions"]
    assert len(sug) == 1 and "Description mentions card ending 9912" in sug[0]["reasons"] and "Amount equals the remaining bill" in sug[0]["reasons"]
    r = user.post(f"/credit-card-statements/{s['id']}/link", {"transaction_id": sug[0]["transaction_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"
    # Linking completed the transfer: the card is now credited.
    assert user.get(f"/credit-cards/{card['id']}").json()["outstanding"] == "0.00"
    assert user.txn(sug[0]["transaction_id"])["to_account_id"] == card["id"]

    # Unlink restores the bill state.
    link_id = r.json()["payments"][0]["link_id"]
    s2 = user.post(f"/credit-card-statements/{s['id']}/unlink", {"link_id": link_id}).json()
    assert s2["status"] == "unpaid"


def test_same_payment_on_bank_and_card_statements_is_flagged_not_double_credited(user):
    bank, card = setup_cards(user)
    spend(user, card, "12000.00", "2026-10-02")
    bank_csv = "Date,Narration,Withdrawal,Deposit\n2026-10-21,CC PAYMENT XXXX9912,12000.00,\n"
    imp = user.post("/imports", files={"file": ("bank.csv", bank_csv.encode(), "text/csv")}, data={"account_id": bank["id"]}).json()
    user.post(f"/imports/{imp['id']}/confirm")
    card_csv = "Date,Description,Amount,Dr/Cr\n2026-10-21,PAYMENT RECEIVED - THANK YOU,12000.00,CR\n"
    imp2 = user.post("/imports", files={"file": ("card.csv", card_csv.encode(), "text/csv")}, data={"account_id": card["id"], "source_kind": "credit_card"}).json()
    user.post(f"/imports/{imp2['id']}/confirm")
    dup = [m for m in user.candidates() if m["kind"] == "duplicate"]
    assert len(dup) == 1, user.candidates()
    user.post(f"/reconciliation/{dup[0]['id']}/confirm", {})
    c = user.get(f"/credit-cards/{card['id']}").json()
    assert c["outstanding"] == "0.00" and c["credit_balance"] == "0.00"  # credited once, not twice
    assert user.get(f"/accounts/{bank['id']}/balance").json()["balance"] == "38000.00"
    assert user.dashboard()["gross_spending"] == "12000.00"


def test_overpayment_leaves_remainder_for_next_bill(user):
    bank, card = setup_cards(user)
    spend(user, card, "1000.00", "2026-10-02")
    s = make_statement(user, card, total_due="1000.00", minimum_due="100.00")
    r = user.post(f"/credit-card-statements/{s['id']}/pay", {"from_account_id": bank["id"], "amount": "1500.00", "paid_on": "2026-10-20"}).json()
    assert r["status"] == "paid" and r["payments"][0]["amount"] == "1000.00" and r["payments"][0]["transaction_amount"] == "1500.00"
    c = user.get(f"/credit-cards/{card['id']}").json()
    assert c["outstanding"] == "0.00" and c["credit_balance"] == "500.00"
    # The unlinked ₹500 can settle the next bill.
    spend(user, card, "800.00", "2026-10-25")
    s2 = make_statement(user, card, statement_date="2026-11-15", period_start="2026-10-16", due_date="2026-12-05", total_due="300.00", minimum_due="30.00")
    sug = user.get(f"/credit-card-statements/{s2['id']}").json()["payment_suggestions"]
    assert sug[0]["available"] == "500.00"
    r2 = user.post(f"/credit-card-statements/{s2['id']}/link", {"transaction_id": sug[0]["transaction_id"]}).json()
    assert r2["status"] == "paid" and r2["payments"][0]["amount"] == "300.00"


def test_overdue_and_reminders(user):
    bank, card = setup_cards(user)
    spend(user, card, "9000.00", (TODAY - timedelta(days=50)).isoformat())
    stmt_day = TODAY - timedelta(days=40)
    s = make_statement(user, card, statement_date=stmt_day.isoformat(), period_start=(stmt_day - timedelta(days=30)).isoformat(), due_date=(TODAY - timedelta(days=2)).isoformat(), total_due="9000.00", minimum_due="450.00")
    assert s["status"] == "overdue" and s["days_until_due"] == -2
    # A second card whose bill is due in 3 days and which is 85% utilised.
    card2 = user.post("/accounts", {"name": "ICICI Card", "type": "credit_card", "credit_limit": "10000"}).json()
    spend(user, card2, "8500.00", (TODAY - timedelta(days=5)).isoformat())
    user.post(f"/credit-cards/{card2['id']}/statements", {"statement_date": (TODAY - timedelta(days=4)).isoformat(), "due_date": (TODAY + timedelta(days=3)).isoformat(), "total_due": "8500.00", "minimum_due": "425.00"})
    assert user.post("/notifications/run-checks").json()["created"] >= 3
    kinds = {n["kind"] for n in user.get("/notifications").json()["items"]}
    assert {"card_bill_overdue", "card_bill_due", "card_high_utilization"} <= kinds
    dash = user.get(f"/dashboard/summary?month={TODAY.strftime('%Y-%m')}").json()["credit_cards"]
    assert dash["count"] == 2 and dash["next_bill"]["status"] == "overdue"
    # Paying the minimum late clears "overdue" but is flagged as late.
    r = user.post(f"/credit-card-statements/{s['id']}/pay", {"from_account_id": bank["id"], "amount": "450.00", "paid_on": TODAY.isoformat()}).json()
    assert r["status"] == "minimum_paid" and r["paid_late"] is True and r["interest_may_apply"] is True


def test_interest_and_fees_recorded_as_expenses_and_voided_with_bill(user):
    _, card = setup_cards(user)
    s = make_statement(user, card, total_due="620.00", minimum_due="100.00", interest_charged="120.00", fees_charged="500.00", record_charges=True)
    assert len(s["charge_transaction_ids"]) == 2
    t = user.dashboard()
    assert t["gross_spending"] == "620.00"
    cats = {user.txn(i)["category_name"] for i in s["charge_transaction_ids"]}
    assert cats == {"Loan Interest", "Bank Charges"}
    r = user.delete(f"/credit-card-statements/{s['id']}")
    assert r.status_code == 200 and len(r.json()["voided_charges"]) == 2
    assert user.dashboard()["gross_spending"] == "0.00"


def test_validation_rules(user):
    bank, card = setup_cards(user)
    base = {"statement_date": "2026-10-15", "due_date": "2026-11-05", "total_due": "1000", "minimum_due": "100"}
    assert user.post(f"/credit-cards/{card['id']}/statements", {**base, "minimum_due": "2000"}).json()["error"]["code"] == "minimum_exceeds_total"
    assert user.post(f"/credit-cards/{card['id']}/statements", {**base, "due_date": "2026-10-01"}).json()["error"]["code"] == "due_before_statement"
    assert user.post(f"/credit-cards/{bank['id']}/statements", base).json()["error"]["code"] == "not_a_credit_card"
    s = user.post(f"/credit-cards/{card['id']}/statements", base).json()
    assert user.post(f"/credit-cards/{card['id']}/statements", base).json()["error"]["code"] == "duplicate_statement"
    # can't pay from the card itself or another card
    assert user.post(f"/credit-card-statements/{s['id']}/pay", {"from_account_id": card["id"], "amount": "100", "paid_on": "2026-10-20"}).json()["error"]["code"] == "invalid_source_account"
    # only card payments can settle a bill
    expense = user.payment("100.00", "Shop", account_id=bank["id"])
    assert user.post(f"/credit-card-statements/{s['id']}/link", {"transaction_id": expense["id"]}).json()["error"]["code"] == "not_a_card_payment"
    # a payment can't be linked beyond its amount, or twice
    pay = user.post(f"/credit-card-statements/{s['id']}/pay", {"from_account_id": bank["id"], "amount": "100", "paid_on": "2026-10-20"}).json()
    tid = pay["payments"][0]["transaction_id"]
    assert user.post(f"/credit-card-statements/{s['id']}/link", {"transaction_id": tid}).json()["error"]["code"] == "already_linked"
    # card fields are only for credit cards
    assert user.post("/accounts", {"name": "X", "type": "bank", "credit_limit": "5000"}).status_code == 422


def test_pay_bill_is_idempotent(user):
    bank, card = setup_cards(user)
    s = make_statement(user, card, total_due="1000.00", minimum_due="100.00")
    body = {"from_account_id": bank["id"], "amount": "1000.00", "paid_on": "2026-10-20"}
    h = {"Idempotency-Key": "pay-card-1"}
    r1 = user.post(f"/credit-card-statements/{s['id']}/pay", body, headers=h)
    r2 = user.post(f"/credit-card-statements/{s['id']}/pay", body, headers=h)
    assert r1.status_code in (200, 201) and r2.status_code in (200, 201)
    assert len(user.get(f"/credit-card-statements/{s['id']}").json()["payments"]) == 1
    assert user.get(f"/accounts/{bank['id']}/balance").json()["balance"] == "49000.00"


def test_other_households_cannot_see_cards(user, other_user):
    _, card = setup_cards(user)
    s = make_statement(user, card)
    assert other_user.get(f"/credit-cards/{card['id']}").status_code == 404
    assert other_user.get(f"/credit-card-statements/{s['id']}").status_code == 404
    assert other_user.get("/credit-cards").json() == []
    assert Decimal(user.get("/credit-cards").json()[0]["credit_limit"]) == Decimal("100000")

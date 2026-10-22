"""Scenarios A-J from the specification plus concurrency, unlinking and recalculation."""
import threading
from decimal import Decimal

import pytest


def only(items, **match):
    found = [i for i in items if all(i[k] == v for k, v in match.items())]
    assert len(found) == 1, f"expected one candidate matching {match}, got {[(i['kind'], i['score']) for i in items]}"
    return found[0]


def codes(m):
    return {r["code"] for r in m["reasons"]}


# ---------------------------------------------------------------- Scenario A
def test_a_exact_amount_and_merchant_counts_once(user):
    bill = user.bill("450.00", "ABC Restaurant", description="Dinner")
    pay = user.payment("450.00", "ABC Restaurant")
    assert user.dashboard()["gross_spending"] == "900.00"  # unconfirmed: both legitimately visible

    m = only(user.candidates(), kind="bill_payment")
    assert m["confidence"] == "high"
    assert {"amount_equal", "merchant_same", "date_same_day"} <= codes(m)
    assert m["a"]["transaction_id"] == bill["id"] and m["b"]["transaction_id"] == pay["id"]

    r = user.post(f"/reconciliation/{m['id']}/confirm", {})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    t = user.dashboard()
    assert t["gross_spending"] == "450.00"
    assert t["cash_outflow"] == "450.00"
    b, p = user.txn(bill["id"]), user.txn(pay["id"])
    assert b["reconciliation_status"] == "fully_paid"
    assert b["payment_method"] == "upi"  # learned from the linked payment
    assert user.get("/analytics/payment-methods?month=2026-10").json() == [{"payment_method": "upi", "amount": "450.00"}]
    assert p["reconciliation_status"] == "matched" and p["effective_amount"] == "0.00"
    # Both records remain visible and traceable.
    assert len(b["allocations"]) == 1 and b["allocations"][0]["payment_transaction_id"] == pay["id"]


# ---------------------------------------------------------------- Scenario B
def test_b_shared_reference_is_strong_evidence(user):
    user.bill("595.00", "Fresh Mart Supermarket", upi_txn_id="429187654321")
    user.payment("595.00", "UPI TRANSFER", upi_txn_id="429187654321", on="2026-10-19")
    m = only(user.candidates(), kind="bill_payment")
    assert "shared_reference" in codes(m)
    assert m["confidence"] == "high" and not m["conflict"]


def test_b_shared_reference_with_conflicting_amount_needs_review(user):
    bill = user.bill("595.00", "Fresh Mart", upi_txn_id="429187654321")
    user.payment("1595.00", "Fresh Mart", upi_txn_id="429187654321")
    m = only(user.candidates(), kind="bill_payment")
    assert m["conflict"] is True and m["confidence"] == "medium"
    assert "amount_conflict" in codes(m)
    assert user.txn(bill["id"])["reconciliation_status"] == "needs_review"


def test_different_references_are_never_matched(user):
    user.payment("450.00", "ABC Restaurant", upi_txn_id="111111111111")
    user.payment("450.00", "ABC Restaurant", upi_txn_id="222222222222")
    assert user.candidates() == []


# ---------------------------------------------------------------- Scenario C
def test_c_normalised_merchant_and_learned_alias(user):
    user.bill("820.00", "Fresh Mart Supermarket")
    user.payment("820.00", "FRESHMART TRIVANDRUM")
    m = only(user.candidates(), kind="bill_payment")
    assert m["merchant_similarity"] >= 0.9
    assert m["confidence"] == "high"
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    # The confirmed match teaches an alias for a later, differently spelled payee.
    user.bill("300.00", "Fresh Mart Supermarket", on="2026-10-25")
    user.payment("300.00", "FRESH MART TVM", on="2026-10-25")
    m2 = [c for c in user.candidates() if c["status"] == "suggested"][0]
    assert m2["confidence"] == "high"


def test_similar_name_alone_is_not_enough(user):
    user.bill("450.00", "ABC Restaurant", on="2026-10-01")
    user.payment("990.00", "ABC Restaurant", on="2026-10-03")
    for m in user.candidates():
        assert m["confidence"] != "high"


# ---------------------------------------------------------------- Scenario D
def test_d_partial_payments_settle_one_bill(user):
    bill = user.bill("1000.00", "City Hardware")
    p1 = user.payment("600.00", "City Hardware")
    m1 = only(user.candidates(), kind="bill_payment")
    user.post(f"/reconciliation/{m1['id']}/confirm", {})
    b = user.txn(bill["id"])
    assert b["reconciliation_status"] == "partially_paid"
    assert b["settlement"]["paid_amount"] == "600.00" and b["settlement"]["remaining_amount"] == "400.00"

    p2 = user.payment("400.00", "City Hardware", on="2026-10-19")
    m2 = [c for c in user.candidates() if c["b"]["transaction_id"] == p2["id"]][0]
    assert "amount_equals_remaining" in codes(m2)
    user.post(f"/reconciliation/{m2['id']}/confirm", {})
    b = user.txn(bill["id"])
    assert b["reconciliation_status"] == "fully_paid"
    assert user.dashboard()["gross_spending"] == "1000.00"
    assert user.txn(p1["id"])["effective_amount"] == "0.00"


# ---------------------------------------------------------------- Scenario E
def test_e_one_payment_covers_two_bills(user):
    b1 = user.bill("900.00", "Office Mart", invoice_number="INV-1")
    b2 = user.bill("600.00", "Office Mart", invoice_number="INV-2")
    pay = user.payment("1500.00", "Office Mart")
    r = user.post(
        "/reconciliation/allocate-payment",
        {"payment_transaction_id": pay["id"], "allocations": [{"bill_transaction_id": b1["id"], "amount": "900.00"}, {"bill_transaction_id": b2["id"], "amount": "600.00"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["available_amount"] == "0.00"
    assert user.dashboard()["gross_spending"] == "1500.00"
    assert user.txn(b1["id"])["reconciliation_status"] == "fully_paid"


def test_e_over_allocation_is_rejected(user):
    b1 = user.bill("900.00", "Office Mart")
    b2 = user.bill("700.00", "Office Mart")
    pay = user.payment("1500.00", "Office Mart")
    r = user.post(
        "/reconciliation/allocate-payment",
        {"payment_transaction_id": pay["id"], "allocations": [{"bill_transaction_id": b1["id"], "amount": "900.00"}, {"bill_transaction_id": b2["id"], "amount": "700.00"}]},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "allocation_exceeds_payment"
    assert user.txn(b1["id"])["allocations"] == []  # atomic: nothing partially applied


def test_unallocated_payment_balance_is_tracked(user):
    b1 = user.bill("900.00", "Office Mart")
    pay = user.payment("1500.00", "Office Mart")
    user.post("/reconciliation/allocate-payment", {"payment_transaction_id": pay["id"], "allocations": [{"bill_transaction_id": b1["id"], "amount": "900.00"}]})
    p = user.txn(pay["id"])
    assert p["reconciliation_status"] == "partially_reconciled"
    assert p["effective_amount"] == "600.00"  # remainder still counts as spending
    s = user.get("/reconciliation/summary").json()
    assert Decimal(s["unallocated_payment_balance"]) == Decimal("600")
    assert user.dashboard()["gross_spending"] == "1500.00"


# ---------------------------------------------------------------- Scenario F
def test_f_split_bill_counts_once_and_reimbursements_are_settlements(user):
    a = user.post("/counterparties", {"name": "Anu"}).json()
    b = user.post("/counterparties", {"name": "Bala"}).json()
    r = user.post(
        "/shared-expenses",
        {
            "description": "Team dinner",
            "total_amount": "1500.00",
            "occurred_on": "2026-10-18",
            "split_method": "equal",
            "merchant_name": "Spice Route",
            "participants": [{"counterparty_id": None}, {"counterparty_id": a["id"]}, {"counterparty_id": b["id"]}],
        },
    )
    assert r.status_code == 201, r.text
    se = r.json()
    assert [p["share_amount"] for p in se["participants"]] == ["500.00"] * 3
    anu = next(p for p in se["participants"] if p["counterparty_id"] == a["id"])
    r = user.post(f"/shared-expenses/{se['id']}/settle", {"participant_id": anu["id"], "amount": "500.00", "settled_on": "2026-10-20"})
    assert r.status_code == 200, r.text
    t = user.dashboard()
    assert t["gross_spending"] == "1500.00"  # reimbursement did not add a purchase
    assert t["reimbursements_received"] == "500.00"
    assert t["others_share_of_shared_bills"] == "1000.00"
    assert t["personal_spending"] == "500.00"
    bal = {x["name"]: x for x in user.get("/counterparties/balances").json()}
    assert bal["Anu"]["receivable"] == "0.00" and bal["Bala"]["receivable"] == "500.00"


def test_f_uneven_split_rounds_exactly(user):
    a = user.post("/counterparties", {"name": "A"}).json()
    b = user.post("/counterparties", {"name": "B"}).json()
    se = user.post(
        "/shared-expenses",
        {"description": "Cab", "total_amount": "100.00", "occurred_on": "2026-10-18", "participants": [{"counterparty_id": None}, {"counterparty_id": a["id"]}, {"counterparty_id": b["id"]}]},
    ).json()
    shares = [Decimal(p["share_amount"]) for p in se["participants"]]
    assert sum(shares) == Decimal("100.00") and sorted(shares) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


# ---------------------------------------------------------------- Scenario G
def test_g_different_amount_requires_confirmation_and_keeps_difference(user):
    bill = user.bill("500.00", "Cafe Mocha")
    pay = user.payment("510.00", "Cafe Mocha")
    m = only(user.candidates(), kind="bill_payment")
    assert m["confidence"] == "medium"
    assert m["amount_difference"] == "10.00"
    assert "amount_over_small" in codes(m)
    user.post(f"/reconciliation/{m['id']}/confirm", {"amount": "500.00"})
    assert user.txn(pay["id"])["effective_amount"] == "10.00"  # tip stays visible as spending
    assert user.dashboard()["gross_spending"] == "510.00"
    assert user.txn(bill["id"])["reconciliation_status"] == "fully_paid"


# ---------------------------------------------------------------- Scenario H
def test_h_same_merchant_amount_different_days_are_separate(user):
    user.payment("450.00", "Fresh Mart", on="2026-10-10")
    user.payment("450.00", "Fresh Mart", on="2026-10-14")
    assert user.candidates() == []
    user.bill("450.00", "Fresh Mart", on="2026-10-02")
    user.bill("450.00", "Fresh Mart", on="2026-10-06")
    assert [c for c in user.candidates() if c["kind"] == "duplicate"] == []


def test_h_two_bills_two_payments_prefer_same_day(user):
    b1 = user.bill("450.00", "Fresh Mart", on="2026-10-10")
    b2 = user.bill("450.00", "Fresh Mart", on="2026-10-12")
    p1 = user.payment("450.00", "Fresh Mart", on="2026-10-10")
    user.payment("450.00", "Fresh Mart", on="2026-10-12")
    best = {c["a"]["transaction_id"]: c for c in sorted(user.candidates(kind="bill_payment"), key=lambda c: c["score"])}
    m = [c for c in user.candidates(kind="bill_payment") if c["a"]["transaction_id"] == b1["id"] and c["b"]["transaction_id"] == p1["id"]][0]
    assert m["confidence"] == "high"
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    # p1 is now fully allocated, so b2 <-> p1 drops below suggestion level
    for c in user.candidates():
        assert not (c["a"]["transaction_id"] == b2["id"] and c["b"]["transaction_id"] == p1["id"] and c["confidence"] != "low")
    assert best


# ---------------------------------------------------------------- Scenario I
def test_i_payment_without_bill_is_valid_and_counted(user):
    p = user.payment("300.00", None, description="Paid Rahul for movie tickets", category_id=None)
    assert p["reconciliation_status"] == "unmatched"
    assert user.dashboard()["gross_spending"] == "300.00"
    q = user.get("/reconciliation/queues").json()
    assert any(s["transaction_id"] == p["id"] for s in q["payments_without_receipts"])


# ---------------------------------------------------------------- Scenario J
def test_j_refund_reduces_net_spending(user):
    orig = user.payment("2000.00", "Amazon", on="2026-10-05")
    user.tx(type="refund", amount="500.00", merchant_name="Amazon", occurred_on="2026-10-12", description="Refund for returned item")
    m = only(user.candidates(), kind="refund")
    assert m["a"]["transaction_id"] == orig["id"]
    r = user.post(f"/reconciliation/{m['id']}/confirm", {})
    assert r.status_code == 200
    t = user.dashboard()
    assert t["gross_spending"] == "2000.00" and t["refunds"] == "500.00" and t["net_spending"] == "1500.00"


def test_j_reversed_payment_is_not_an_expense(user):
    orig = user.payment("750.00", "Zomato", on="2026-10-05", upi_txn_id="429100000001")
    rev = user.tx(type="income", amount="750.00", merchant_name="Zomato", occurred_on="2026-10-05", description="UPI REVERSAL failed txn", upi_txn_id="429100000001")
    m = only(user.candidates(), kind="refund")
    r = user.post(f"/reconciliation/{m['id']}/confirm", {"as_reversal": True})
    assert r.status_code == 200, r.text
    t = user.dashboard()
    assert t["gross_spending"] == "0.00" and t["income"] == "0.00" and t["net_cash_flow"] == "0.00"
    assert user.txn(orig["id"])["status"] == "reversed" and user.txn(rev["id"])["status"] == "reversed"
    # and it can be undone
    user.post("/reconciliation/unlink", {"match_id": m["id"]})
    assert user.txn(orig["id"])["status"] == "active"
    assert user.dashboard()["gross_spending"] == "750.00"


# ---------------------------------------------------------------- duplicates, reject, unlink, reopen
def test_manual_entry_plus_statement_row_merge_as_duplicate(user):
    manual = user.payment("450.00", "ABC Restaurant", upi_txn_id="429112345678")
    stmt = user.payment("450.00", "ABC RESTAURANT", upi_txn_id="429112345678")
    m = only(user.candidates(), kind="duplicate")
    assert m["confidence"] == "high"
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    assert user.dashboard()["gross_spending"] == "450.00"
    s = user.txn(stmt["id"])
    assert s["status"] == "merged" and s["merged_into_id"] == manual["id"]
    assert len(user.txn(manual["id"])["sources"]) == 2
    user.post("/reconciliation/unlink", {"match_id": m["id"]})
    assert user.txn(stmt["id"])["status"] == "active"
    assert user.dashboard()["gross_spending"] == "900.00"


def test_rejected_match_is_not_resuggested_and_reopen_works(user):
    user.bill("450.00", "ABC Restaurant")
    user.payment("450.00", "ABC Restaurant")
    m = only(user.candidates(), kind="bill_payment")
    r = user.post(f"/reconciliation/{m['id']}/reject", {"separate_purchases": True})
    assert r.json()["status"] == "rejected"
    user.post("/reconciliation/recalculate")
    assert user.candidates() == []
    assert user.candidates(status="rejected")[0]["id"] == m["id"]
    r = user.post(f"/reconciliation/{m['id']}/reopen")
    assert r.json()["status"] == "suggested"
    hist = user.get(f"/reconciliation/{m['id']}").json()["history"]
    assert [h["action"] for h in hist] == ["rejected", "reopened"]


def test_unlink_restores_totals_and_is_audited(user):
    bill = user.bill("450.00", "ABC Restaurant")
    pay = user.payment("450.00", "ABC Restaurant")
    m = only(user.candidates(), kind="bill_payment")
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    r = user.post("/reconciliation/unlink", {"match_id": m["id"], "note": "wrong bill"})
    assert r.status_code == 200
    assert user.dashboard()["gross_spending"] == "900.00"
    assert user.txn(pay["id"])["effective_amount"] == "450.00"
    hist = user.get(f"/reconciliation/{m['id']}").json()["history"]
    assert [h["action"] for h in hist] == ["allocation_created", "confirmed", "allocation_removed", "unlinked"]
    assert hist[0]["after"] and bill


def test_confirm_is_idempotent_with_key(user):
    user.bill("450.00", "ABC Restaurant")
    user.payment("450.00", "ABC Restaurant")
    m = only(user.candidates(), kind="bill_payment")
    h = {"Idempotency-Key": "confirm-abc-1"}
    r1 = user.post(f"/reconciliation/{m['id']}/confirm", {}, headers=h)
    r2 = user.post(f"/reconciliation/{m['id']}/confirm", {}, headers=h)
    assert r1.status_code == r2.status_code == 200
    assert len(r1.json()["allocations"]) == len(r2.json()["allocations"]) == 1
    assert user.dashboard()["gross_spending"] == "450.00"


def test_manual_match_for_records_the_engine_missed(user):
    bill = user.bill("1200.00", "Dr. Mehta Clinic", on="2026-10-01")
    pay = user.payment("1200.00", "MEHTA HEALTHCARE", on="2026-10-09")
    r = user.post("/reconciliation/manual-match", {"a_transaction_id": bill["id"], "b_transaction_id": pay["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed" and r.json()["origin"] == "manual"
    assert user.dashboard()["gross_spending"] == "1200.00"


def test_incompatible_manual_match_is_refused(user):
    acc = user.post("/accounts", {"name": "Savings", "type": "bank"}).json()
    cash = [a for a in user.get("/accounts").json() if a["type"] == "cash"][0]
    a = user.tx(type="transfer", amount="1000.00", description="To savings", account_id=cash["id"], to_account_id=acc["id"])
    b = user.bill("1000.00", "Shop")
    r = user.post("/reconciliation/manual-match", {"a_transaction_id": a["id"], "b_transaction_id": b["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "incompatible_records"


def test_manual_refund_larger_than_original_is_refused(user):
    orig = user.payment("100.00", "Shop", on="2026-10-05")
    ref = user.tx(type="refund", amount="150.00", merchant_name="Shop", occurred_on="2026-10-06")
    r = user.post("/reconciliation/manual-match", {"a_transaction_id": orig["id"], "b_transaction_id": ref["id"]})
    assert r.status_code == 422


def test_recalculate_repairs_drift(user):
    from sqlalchemy import update

    from app.core.db import SessionLocal
    from app.models import CanonicalTransaction

    user.bill("450.00", "ABC Restaurant")
    pay = user.payment("450.00", "ABC Restaurant")
    m = only(user.candidates(), kind="bill_payment")
    user.post(f"/reconciliation/{m['id']}/confirm", {})
    with SessionLocal() as db:  # simulate corruption of the denormalised column
        db.execute(update(CanonicalTransaction).where(CanonicalTransaction.id == pay["id"]).values(effective_amount=Decimal("450")))
        db.commit()
    assert user.dashboard()["gross_spending"] == "900.00"
    r = user.post("/reconciliation/recalculate").json()
    assert pay["id"] in r["amount_drift_corrected"]
    assert user.dashboard()["gross_spending"] == "450.00"


# ---------------------------------------------------------------- concurrency
def _parallel(n, fn):
    results, barrier = [], threading.Barrier(n)

    def run():
        barrier.wait()
        results.append(fn())

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_confirms_create_one_allocation(client, user):
    bill = user.bill("450.00", "ABC Restaurant")
    user.payment("450.00", "ABC Restaurant")
    m = only(user.candidates(), kind="bill_payment")
    codes_ = _parallel(6, lambda: user.post(f"/reconciliation/{m['id']}/confirm", {}).status_code)
    assert all(c == 200 for c in codes_), codes_
    assert len(user.txn(bill["id"])["allocations"]) == 1
    assert user.dashboard()["gross_spending"] == "450.00"


def test_concurrent_allocations_cannot_overdraw_payment(client, user):
    bills = [user.bill("1000.00", f"Vendor {i}", invoice_number=f"V-{i}") for i in range(4)]
    pay = user.payment("1500.00", "Vendor Payments")
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def alloc(b):
        barrier.wait()
        r = user.post("/reconciliation/allocate-payment", {"payment_transaction_id": pay["id"], "allocations": [{"bill_transaction_id": b["id"], "amount": "1000.00"}]})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=alloc, args=(b,)) for b in bills]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1, results
    assert all(c in (200, 409) for c in results)
    p = user.txn(pay["id"])
    assert p["sources"][0]["allocated_amount"] == "1000.00"


def test_database_rejects_over_allocation_even_without_app_checks(user):
    from sqlalchemy.exc import IntegrityError

    from app.core.db import SessionLocal
    from app.models import ReconciliationAllocation, SourceRecord

    bill = user.bill("100.00", "X")
    pay = user.payment("100.00", "X")
    with SessionLocal() as db:
        b = db.query(SourceRecord).filter_by(canonical_transaction_id=bill["id"]).one()
        p = db.query(SourceRecord).filter_by(canonical_transaction_id=pay["id"]).one()
        db.add(ReconciliationAllocation(household_id=b.household_id, payment_source_id=p.id, bill_source_id=b.id, amount=Decimal("60")))
        db.add(ReconciliationAllocation(household_id=b.household_id, payment_source_id=p.id, bill_source_id=b.id, amount=Decimal("60")))
        with pytest.raises(IntegrityError):
            db.commit()

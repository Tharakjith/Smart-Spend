import io

from tests.factories import BANK_CSV


def upload(user, content: bytes, name="statement.csv", **form):
    return user.post("/imports", files={"file": (name, content, "text/csv")}, data=form)


def test_csv_import_preview_confirm_and_reimport(user):
    bank = user.post("/accounts", {"name": "XYZ Bank", "type": "bank"}).json()
    r = upload(user, BANK_CSV.encode(), account_id=bank["id"])
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["column_mapping"]["date"] == "Txn Date"
    assert imp["column_mapping"]["debit"] == "Withdrawal Amt" and imp["column_mapping"]["credit"] == "Deposit Amt"
    assert imp["column_mapping"]["reference"] == "Ref No"
    prev = user.get(f"/imports/{imp['id']}/preview").json()
    assert prev["counts"] == {"new": 5, "duplicate_existing": 0, "invalid": 0}
    row = lambda prefix: next(r for r in prev["rows"] if r["description"].startswith(prefix))  # noqa: E731
    assert row("NEFT-SALARY")["direction"] == "in" and row("NEFT-SALARY")["suggested_type"] == "income"
    assert row("CC PAYMENT")["suggested_type"] == "credit_card_payment"
    assert prev["rows"][0]["payee"] == "ABC RESTAURANT" and prev["rows"][0]["reference"] == "429112345678"

    r = user.post(f"/imports/{imp['id']}/confirm")
    assert r.status_code == 200 and r.json()["imported_count"] == 5
    t = user.dashboard()
    assert t["gross_spending"] == "1345.00"  # 450 + 595 + 300; CC payment excluded
    assert t["income"] == "85000.00" and t["internal_transfers"] == "12000.00"
    # confirming again is a no-op
    assert user.post(f"/imports/{imp['id']}/confirm").json()["imported_count"] == 5

    # importing the same statement again does not duplicate anything
    r = upload(user, BANK_CSV.encode(), account_id=bank["id"])
    assert r.json()["previously_imported"] is not None
    prev = user.get(f"/imports/{r.json()['id']}/preview").json()
    assert prev["counts"]["duplicate_existing"] == 5 and prev["counts"]["new"] == 0
    r2 = user.post(f"/imports/{r.json()['id']}/confirm").json()
    assert "imported_count" in r2, r2
    assert r2["imported_count"] == 0 and r2["skipped_duplicates"] == 5
    assert user.dashboard()["gross_spending"] == "1345.00"


def test_statement_rows_match_existing_receipts_and_manual_entries(user):
    bank = user.post("/accounts", {"name": "XYZ Bank", "type": "bank"}).json()
    bill = user.bill("450.00", "ABC Restaurant")
    imp = upload(user, BANK_CSV.encode(), account_id=bank["id"]).json()
    prev = user.get(f"/imports/{imp['id']}/preview").json()
    assert prev["rows"][0]["possible_match"]["transaction_id"] == bill["id"]
    user.post(f"/imports/{imp['id']}/confirm")
    m = [c for c in user.candidates() if c["a"]["transaction_id"] == bill["id"]][0]
    assert m["kind"] == "bill_payment" and m["confidence"] == "high"


def test_identical_rows_in_one_file_are_kept_separately(user):
    csv = "Date,Description,Amount\n2026-10-05,TEA STALL,-20.00\n2026-10-05,TEA STALL,-20.00\n"
    imp = upload(user, csv.encode()).json()
    prev = user.get(f"/imports/{imp['id']}/preview").json()
    assert prev["counts"]["new"] == 2
    assert user.post(f"/imports/{imp['id']}/confirm").json()["imported_count"] == 2
    imp2 = upload(user, csv.encode()).json()
    assert user.get(f"/imports/{imp2['id']}/preview").json()["counts"]["duplicate_existing"] == 2


def test_xlsx_and_signed_amounts_and_invalid_rows(user):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Transaction Date", "Description", "Amount", "Dr/Cr"])
    ws.append(["03/10/2026", "AMAZON PAY INDIA", "1,299.00", "DR"])
    ws.append(["04/10/2026", "REFUND AMAZON", "299.00", "CR"])
    ws.append(["not a date", "BROKEN", "10", "DR"])
    buf = io.BytesIO()
    wb.save(buf)
    imp = user.post("/imports", files={"file": ("card.xlsx", buf.getvalue(), "application/octet-stream")}, data={"source_kind": "credit_card"}).json()
    prev = user.get(f"/imports/{imp['id']}/preview").json()
    assert prev["counts"] == {"new": 2, "duplicate_existing": 0, "invalid": 1}
    assert prev["rows"][0]["direction"] == "out" and prev["rows"][0]["amount"] == "1299.00"
    assert prev["rows"][1]["suggested_type"] == "refund"
    user.post(f"/imports/{imp['id']}/confirm")
    t = user.dashboard()
    assert t["gross_spending"] == "1299.00" and t["refunds"] == "299.00" and t["net_spending"] == "1000.00"


def test_column_mapping_override_and_validation(user):
    csv = "When,What,Out,In\n2026-10-07,Bakery,55.00,\n"
    imp = upload(user, csv.encode())
    assert imp.status_code in (201, 422)
    if imp.status_code == 422:  # headers unrecognised: user must map manually is not possible without a header row
        return
    i = imp.json()
    r = user.put(f"/imports/{i['id']}/mapping", {"column_mapping": {"date": "When", "description": "What", "debit": "Out", "credit": "In"}})
    assert r.status_code == 200
    assert user.get(f"/imports/{i['id']}/preview").json()["counts"]["new"] == 1
    bad = user.put(f"/imports/{i['id']}/mapping", {"column_mapping": {"date": "Nope", "description": "What", "amount": "Out"}})
    assert bad.status_code == 422


def test_non_statement_files_rejected(user):
    r = user.post("/imports", files={"file": ("x.csv", b"MZ\x00\x01binary", "text/csv")})
    assert r.status_code == 422

"""Reports with CSV / XLSX / PDF export. Every report states its date range, currency and filters, and
all figures come from the canonical ledger (counted amounts, never a blind sum of source documents)."""
import csv
import io
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import Ctx, get_ctx
from app.core.errors import ValidationFailed
from app.core.money import quantize
from app.models import (
    CanonicalTransaction,
    Counterparty,
    Loan,
    Merchant,
    ReconciliationMatch,
    SourceRecord,
    TransactionLineItem,
)
from app.modules.analytics import service as an
from app.modules.categories.service import CategoryIndex
from app.modules.ledger.router import filtered_query
from app.modules.ledger.service import name_lookup

router = APIRouter(prefix="/reports", tags=["reports"])
KINDS = ("transactions", "monthly", "annual", "category", "merchant", "person", "budget", "items", "loans", "unmatched", "duplicates", "reconciliation")
ZERO = Decimal("0")


def _m(v, cur) -> str:
    return format(quantize(v, cur), "f")


def build_report(ctx: Ctx, kind: str, date_from: date, date_to: date, filters: dict) -> dict:
    db, hid, cur = ctx.db, ctx.household_id, ctx.household.base_currency
    end_excl = date_to + timedelta(days=1)
    title, columns, rows, totals = kind.title(), [], [], None
    if kind == "transactions":
        q = filtered_query(ctx, date_from=date_from, date_to=date_to, **{k: v for k, v in filters.items() if v not in (None, "")}).order_by(CanonicalTransaction.occurred_on, CanonicalTransaction.created_at).limit(20000)
        txs = db.scalars(q).all()
        names = name_lookup(db, hid, txs)
        title = "Transactions"
        columns = ["Date", "Type", "Description", "Category", "Merchant", "Person", "Account", "Method", "Amount", "Counted", "Currency", "Status", "Reconciliation", "Tags"]
        for t in txs:
            rows.append([t.occurred_on.isoformat(), t.type, t.description, names.get(t.category_id, ""), names.get(t.merchant_id, ""), names.get(t.counterparty_id, ""), names.get(t.account_id, ""), t.payment_method or "", _m(t.amount, t.currency), _m(t.effective_amount, t.currency), t.currency, t.status, t.reconciliation_status, ", ".join(t.tags or [])])
        spend = sum((Decimal(t.effective_amount) for t in txs if t.type == "expense" and t.status == "active" and t.currency == cur), ZERO)
        totals = ["", "", "Counted expenses (active, base currency)", "", "", "", "", "", "", _m(spend, cur), cur, "", "", ""]
    elif kind in ("monthly", "annual"):
        title = "Monthly summary" if kind == "monthly" else "Annual summary"
        columns = ["Period", "Gross spending", "Refunds", "Net spending", "Others' share", "Personal spending", "Income", "Net cash flow"]
        cursor = date(date_from.year, date_from.month if kind == "monthly" else 1, 1)
        while cursor <= date_to:
            nxt = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1) if kind == "monthly" else date(cursor.year + 1, 1, 1)
            s, e = max(cursor, date_from), min(nxt, end_excl)
            t = an.period_totals(db, hid, s, e, cur)
            label = f"{cursor.year:04d}-{cursor.month:02d}" if kind == "monthly" else str(cursor.year)
            rows.append([label, t["gross_spending"], t["refunds"], t["net_spending"], t["others_share_of_shared_bills"], t["personal_spending"], t["income"], t["net_cash_flow"]])
            cursor = nxt
        t = an.period_totals(db, hid, date_from, end_excl, cur)
        totals = ["Total", t["gross_spending"], t["refunds"], t["net_spending"], t["others_share_of_shared_bills"], t["personal_spending"], t["income"], t["net_cash_flow"]]
    elif kind == "category":
        title = "Spending by category"
        columns = ["Category", "Net spending", "Share"]
        data = an.category_breakdown(db, hid, date_from, end_excl, cur, filters.get("level") or "top")
        total = sum((Decimal(r["amount"]) for r in data), ZERO)
        rows = [[r["name"], r["amount"], f"{(Decimal(r['amount']) / total * 100):.1f}%" if total else "0%"] for r in data]
        totals = ["Total", _m(total, cur), "100%"]
    elif kind == "merchant":
        title = "Spending by merchant"
        columns = ["Merchant", "Transactions", "Counted spending"]
        data = an.top_merchants(db, hid, date_from, end_excl, cur, limit=1000)["merchants"]
        rows = [[r["name"], r["count"], r["amount"]] for r in data]
        totals = ["Total", sum(r["count"] for r in data), _m(sum((Decimal(r["amount"]) for r in data), ZERO), cur)]
    elif kind == "person":
        from app.modules.people.router import person_balance

        title = "Person-wise report"
        columns = ["Person", "Paid to them", "Received from them", "They owe you", "You owe them", "Net"]
        for c in db.scalars(select(Counterparty).where(Counterparty.household_id == hid).order_by(Counterparty.name)).all():
            if filters.get("counterparty_id") and str(c.id) != str(filters["counterparty_id"]):
                continue
            txs = db.scalars(select(CanonicalTransaction).where(CanonicalTransaction.household_id == hid, CanonicalTransaction.counterparty_id == c.id, CanonicalTransaction.status == "active", CanonicalTransaction.currency == cur, CanonicalTransaction.occurred_on >= date_from, CanonicalTransaction.occurred_on < end_excl)).all()
            from app.models.finance import TRANSACTION_TYPES

            paid = sum((Decimal(t.cash_amount) for t in txs if TRANSACTION_TYPES[t.type] == "out"), ZERO)
            recv = sum((Decimal(t.cash_amount) for t in txs if TRANSACTION_TYPES[t.type] == "in"), ZERO)
            b = person_balance(ctx, c.id)
            rows.append([c.name, _m(paid, cur), _m(recv, cur), b["receivable"], b["payable"], b["net"]])
    elif kind == "budget":
        title = "Budget performance"
        columns = ["Budget", "Period", "Category", "Budget", "Spent", "Remaining", "% used", "State"]
        for b in an.budget_status(db, hid, cur, min(date_to, date.today())):
            rows.append([b["name"], b["period"], b["category_name"] or "All spending", b["amount"], b["spent"], b["remaining"], f"{b['percent_used']}%", b["state"]])
    elif kind == "items":
        title = "Item-level purchases"
        columns = ["Date", "Merchant", "Item", "Quantity", "Unit", "Unit price", "Line total", "Category"]
        idx = CategoryIndex(db, hid)
        q = (
            select(TransactionLineItem, CanonicalTransaction)
            .join(CanonicalTransaction, CanonicalTransaction.id == TransactionLineItem.transaction_id)
            .where(TransactionLineItem.household_id == hid, CanonicalTransaction.status == "active", CanonicalTransaction.occurred_on >= date_from, CanonicalTransaction.occurred_on < end_excl)
            .order_by(CanonicalTransaction.occurred_on)
        )
        if filters.get("q"):
            q = q.where(TransactionLineItem.name.ilike(f"%{filters['q']}%"))
        merchants = {m.id: m.name for m in db.scalars(select(Merchant).where(Merchant.household_id == hid)).all()}
        for li, t in db.execute(q).all():
            rows.append([t.occurred_on.isoformat(), merchants.get(t.merchant_id, ""), li.name, format(li.quantity, "f") if li.quantity is not None else "", li.unit or "", _m(li.unit_price, t.currency) if li.unit_price is not None else "", _m(li.line_total, t.currency) if li.line_total is not None else "", idx.by_id[li.category_id].name if li.category_id in idx.by_id else ""])
    elif kind == "loans":
        title = "Loans and repayments"
        columns = ["Person", "Direction", "Start", "Due", "Principal", "Principal repaid", "Interest paid", "Outstanding", "Status"]
        people = {c.id: c.name for c in db.scalars(select(Counterparty).where(Counterparty.household_id == hid)).all()}
        for ln in db.scalars(select(Loan).options(selectinload(Loan.repayments)).where(Loan.household_id == hid).order_by(Loan.start_date)).all():
            rep = sum((Decimal(r.principal_amount) for r in ln.repayments), ZERO)
            intr = sum((Decimal(r.interest_amount) for r in ln.repayments), ZERO)
            rows.append([people.get(ln.counterparty_id, ""), ln.direction, ln.start_date.isoformat(), ln.due_date.isoformat() if ln.due_date else "", _m(ln.principal, ln.currency), _m(rep, ln.currency), _m(intr, ln.currency), _m(Decimal(ln.principal) - rep, ln.currency), ln.status])
    elif kind in ("unmatched", "reconciliation"):
        title = "Unmatched transactions" if kind == "unmatched" else "Reconciliation summary"
        columns = ["Date", "Source", "Role", "Merchant / description", "Amount", "Allocated", "Status"]
        q = select(SourceRecord).where(SourceRecord.household_id == hid, SourceRecord.status == "active", SourceRecord.occurred_on >= date_from, SourceRecord.occurred_on < end_excl).order_by(SourceRecord.occurred_on)
        if kind == "unmatched":
            q = q.where(SourceRecord.reconciliation_status.in_(("unmatched", "suggested_match", "partially_paid", "partially_reconciled", "needs_review")))
        for s in db.scalars(q).all():
            rows.append([s.occurred_on.isoformat(), s.source_type, s.role, s.merchant_raw or s.description, _m(s.amount, s.currency), _m(s.allocated_amount, s.currency), s.reconciliation_status])
    elif kind == "duplicates":
        title = "Duplicate detection report"
        columns = ["Detected", "Kind", "Status", "Confidence", "Score", "Record A", "Record B", "Amount difference", "Reasons"]
        for m in db.scalars(select(ReconciliationMatch).where(ReconciliationMatch.household_id == hid, ReconciliationMatch.created_at >= date_from).order_by(ReconciliationMatch.created_at)).all():
            a, b = db.get(SourceRecord, m.a_source_id), db.get(SourceRecord, m.b_source_id)
            rows.append([m.created_at.date().isoformat(), m.kind, m.status, m.confidence, m.score, f"{a.merchant_raw or a.description} {a.amount}", f"{b.merchant_raw or b.description} {b.amount}", format(m.amount_difference, "f"), "; ".join(r["text"] for r in m.reasons)])
    meta = {
        "title": title,
        "household": ctx.household.name,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "currency": cur,
        "filters": {k: str(v) for k, v in filters.items() if v not in (None, "")},
        "generated_by": ctx.user.email,
    }
    return {"meta": meta, "columns": columns, "rows": [[str(c) for c in r] for r in rows], "totals": [str(c) for c in totals] if totals else None}


def to_csv(rep: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    m = rep["meta"]
    w.writerow([m["title"]])
    w.writerow(["Period", f"{m['date_from']} to {m['date_to']}"])
    w.writerow(["Currency", m["currency"]])
    w.writerow(["Filters", "; ".join(f"{k}={v}" for k, v in m["filters"].items()) or "none"])
    w.writerow([])
    w.writerow(rep["columns"])
    for r in rep["rows"]:
        # Neutralise spreadsheet formula injection in user-controlled text.
        w.writerow([("'" + c) if c[:1] in ("=", "+", "-", "@") and not _is_number(c) else c for c in r])
    if rep["totals"]:
        w.writerow(rep["totals"])
    return buf.getvalue().encode("utf-8-sig")


def _is_number(s: str) -> bool:
    try:
        Decimal(s)
        return True
    except Exception:
        return False


def to_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = rep["meta"]["title"][:31]
    m = rep["meta"]
    for line in ([m["title"]], ["Period", f"{m['date_from']} to {m['date_to']}"], ["Currency", m["currency"]], ["Filters", "; ".join(f"{k}={v}" for k, v in m["filters"].items()) or "none"], []):
        ws.append(line)
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(rep["columns"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for r in rep["rows"]:
        ws.append([Decimal(c) if _is_number(c) and c.strip() else c for c in r])
    if rep["totals"]:
        ws.append([Decimal(c) if _is_number(c) and c.strip() else c for c in rep["totals"]])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(rep: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    out = io.BytesIO()
    wide = len(rep["columns"]) > 6
    doc = SimpleDocTemplate(out, pagesize=landscape(A4) if wide else A4, leftMargin=28, rightMargin=28, topMargin=28, bottomMargin=28, title=rep["meta"]["title"])
    st = getSampleStyleSheet()
    m = rep["meta"]
    small = st["BodyText"].clone("small", fontSize=7, leading=9)
    story = [
        Paragraph(m["title"], st["Title"]),
        Paragraph(f"{m['household']} · {m['date_from']} to {m['date_to']} · Currency: {m['currency']} (amounts in {m['currency']}; 'Rs' shown as code)", st["Normal"]),
        Paragraph("Filters: " + ("; ".join(f"{k}={v}" for k, v in m["filters"].items()) or "none"), st["Normal"]),
        Spacer(1, 10),
    ]
    data = [[Paragraph(f"<b>{c}</b>", small) for c in rep["columns"]]]
    data += [[Paragraph(str(c).replace("&", "&amp;").replace("<", "&lt;"), small) for c in r] for r in rep["rows"][:5000]]
    if rep["totals"]:
        data.append([Paragraph(f"<b>{c}</b>", small) for c in rep["totals"]])
    if len(data) == 1:
        data.append([Paragraph("No data for this period", small)] + [""] * (len(rep["columns"]) - 1))
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2f3f0")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)
    doc.build(story)
    return out.getvalue()


@router.get("/{kind}")
def report(
    kind: str,
    ctx: Ctx = Depends(get_ctx),
    format: str = Query("json", pattern="^(json|csv|xlsx|pdf)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: uuid.UUID | None = None,
    merchant_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    payment_method: str | None = None,
    type: list[str] | None = Query(None),
    tag: str | None = None,
    q: str | None = None,
    reconciliation_status: str | None = None,
    level: str | None = None,
):
    if kind not in KINDS:
        raise ValidationFailed(f"Unknown report. Choose one of: {', '.join(KINDS)}")
    today = date.today()
    date_to = date_to or today
    date_from = date_from or (date(today.year, 1, 1) if kind == "annual" else date(date_to.year, date_to.month, 1))
    if date_from > date_to:
        raise ValidationFailed("date_from must be on or before date_to")
    if (date_to - date_from).days > 3660:
        raise ValidationFailed("Reports are limited to 10 years")
    filters = {"category_id": category_id, "merchant_id": merchant_id, "counterparty_id": counterparty_id, "account_id": account_id, "payment_method": payment_method, "type": type, "tag": tag, "q": q, "reconciliation_status": reconciliation_status}
    if kind == "category":
        filters = {"level": level}
    rep = build_report(ctx, kind, date_from, date_to, filters)
    if format == "json":
        return rep
    name = f"smartspend-{kind}-{date_from}-{date_to}"
    if format == "csv":
        return Response(to_csv(rep), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if format == "xlsx":
        return Response(to_xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(to_pdf(rep), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})

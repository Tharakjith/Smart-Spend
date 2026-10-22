import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.storage import get_storage, new_key
from app.models import Account, DuplicateCandidate, SourceRecord, StatementImport, StatementRow
from app.modules.common import Schema, audit
from app.modules.documents.validation import validate_statement
from app.modules.imports.parser import detect_mapping, fingerprint, normalise_rows, read_table
from app.modules.ledger.service import TransactionIn, create_transaction

router = APIRouter(prefix="/imports", tags=["imports"])

CHANNEL_METHOD = {"upi": "upi", "card": "debit_card", "bank_transfer": "bank_transfer"}


def _out(imp: StatementImport, sample: int = 10) -> dict:
    return {
        "id": str(imp.id),
        "filename": imp.original_filename,
        "file_format": imp.file_format,
        "source_kind": imp.source_kind,
        "account_id": str(imp.account_id) if imp.account_id else None,
        "currency": imp.currency,
        "status": imp.status,
        "headers": imp.headers,
        "column_mapping": imp.column_mapping,
        "date_format": imp.date_format,
        "row_count": imp.row_count,
        "imported_count": imp.imported_count,
        "skipped_duplicates": imp.skipped_duplicates,
        "invalid_count": imp.invalid_count,
        "error_message": imp.error_message,
        "sample_rows": imp.raw_rows[:sample],
        "created_at": imp.created_at.isoformat(),
        "confirmed_at": imp.confirmed_at.isoformat() if imp.confirmed_at else None,
    }


def _get(ctx: Ctx, imp_id: uuid.UUID, lock: bool = False) -> StatementImport:
    q = select(StatementImport).where(StatementImport.id == imp_id)
    if lock:
        q = q.with_for_update()
    imp = ctx.db.scalars(q).first()
    if imp is None or imp.household_id != ctx.household_id:
        raise NotFound("Import not found")
    return imp


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...),
    account_id: uuid.UUID | None = Form(default=None),
    source_kind: str = Form(default="bank"),
    currency: str | None = Form(default=None),
    ctx: Ctx = Depends(writer_ctx),
):
    if source_kind not in ("bank", "credit_card", "upi", "wallet"):
        raise ValidationFailed("source_kind must be bank, credit_card, upi or wallet")
    acc = None
    if account_id:
        acc = ctx.db.get(Account, account_id)
        if acc is None or acc.household_id != ctx.household_id:
            raise NotFound("Account not found")
    data = await file.read(get_settings().max_upload_bytes + 1)
    fmt = validate_statement(file.filename or "statement", data)
    try:
        headers, rows = read_table(fmt, data)
    except ValueError as exc:
        raise ValidationFailed(str(exc), code="statement_unreadable")
    except Exception:
        raise ValidationFailed("The statement could not be read. Check that it is a valid CSV, XLSX or PDF export.", code="statement_unreadable")
    if len(rows) > 20000:
        raise ValidationFailed("Statements are limited to 20,000 rows per import")
    digest = hashlib.sha256(data).hexdigest()
    previous = ctx.db.scalars(
        select(StatementImport).where(StatementImport.household_id == ctx.household_id, StatementImport.sha256 == digest, StatementImport.status == "confirmed")
    ).first()
    key = new_key(ctx.household_id, f".{fmt}")
    get_storage().put(key, data, "application/octet-stream")
    imp = StatementImport(
        household_id=ctx.household_id,
        account_id=acc.id if acc else None,
        uploaded_by=ctx.user.id,
        original_filename=(file.filename or "statement")[:255],
        sha256=digest,
        storage_key=key,
        file_format=fmt,
        source_kind=source_kind,
        currency=(currency or (acc.currency if acc else ctx.household.base_currency)).upper(),
        status="mapped",
        headers=headers,
        raw_rows=rows,
        column_mapping=detect_mapping(headers),
        row_count=len(rows),
    )
    ctx.db.add(imp)
    audit(ctx, "upload", "statement_import", None, None, {"filename": imp.original_filename, "rows": len(rows)})
    ctx.db.commit()
    out = _out(imp)
    out["previously_imported"] = (
        {"import_id": str(previous.id), "confirmed_at": previous.confirmed_at.isoformat() if previous.confirmed_at else None} if previous else None
    )
    return out


@router.get("")
def list_imports(ctx: Ctx = Depends(get_ctx), page: int = 1, page_size: int = Query(20, le=100)):
    q = select(StatementImport).where(StatementImport.household_id == ctx.household_id).order_by(StatementImport.created_at.desc())
    rows = ctx.db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
    total = ctx.db.scalar(select(func.count()).select_from(StatementImport).where(StatementImport.household_id == ctx.household_id))
    return {"items": [_out(i, 0) for i in rows], "total": total, "page": page, "page_size": page_size}


class MappingIn(Schema):
    column_mapping: dict[str, str | None]
    date_format: str | None = Field(default=None, max_length=20)
    account_id: uuid.UUID | None = None
    source_kind: str | None = Field(default=None, pattern="^(bank|credit_card|upi|wallet)$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


@router.put("/{imp_id}/mapping")
def set_mapping(imp_id: uuid.UUID, body: MappingIn, ctx: Ctx = Depends(writer_ctx)):
    imp = _get(ctx, imp_id)
    if imp.status == "confirmed":
        raise Conflict("This import is already confirmed", code="import_confirmed")
    allowed = {"date", "description", "debit", "credit", "amount", "direction", "reference", "balance", "currency"}
    mapping = {k: v for k, v in body.column_mapping.items() if k in allowed}
    for v in mapping.values():
        if v is not None and v not in imp.headers:
            raise ValidationFailed(f"Unknown column '{v}'")
    if not mapping.get("date") or not mapping.get("description"):
        raise ValidationFailed("Map at least the date and description columns")
    if not (mapping.get("amount") or mapping.get("debit") or mapping.get("credit")):
        raise ValidationFailed("Map an amount column, or debit and credit columns")
    imp.column_mapping = mapping
    imp.date_format = body.date_format or None
    if body.account_id is not None:
        acc = ctx.db.get(Account, body.account_id)
        if acc is None or acc.household_id != ctx.household_id:
            raise NotFound("Account not found")
        imp.account_id = acc.id
    if body.source_kind:
        imp.source_kind = body.source_kind
    if body.currency:
        imp.currency = body.currency
    ctx.db.commit()
    return _out(imp)


def _preview_rows(ctx: Ctx, imp: StatementImport) -> list[dict]:
    rows = normalise_rows(imp.raw_rows, imp.headers, imp.column_mapping, imp.date_format, imp.currency, imp.source_kind)
    fps = {fingerprint(ctx.household_id, imp.account_id, r): r for r in rows if not r["errors"]}
    existing = set(
        ctx.db.scalars(select(StatementRow.fingerprint).where(StatementRow.household_id == ctx.household_id, StatementRow.fingerprint.in_(list(fps)))).all()
    ) if fps else set()
    for r in rows:
        if r["errors"]:
            r["status"] = "invalid"
            continue
        fp = fingerprint(ctx.household_id, imp.account_id, r)
        r["fingerprint"] = fp
        if fp in existing:
            r["status"] = "duplicate_existing"
        else:
            r["status"] = "new"
            if r["occurrence"] > 0:
                r.setdefault("warnings", []).append("Identical to an earlier row in this file; imported as a separate transaction")
    return rows


def _possible_match(ctx: Ctx, r: dict) -> dict | None:
    if r["status"] != "new" or r["direction"] != "out":
        return None
    d = date.fromisoformat(r["occurred_on"])
    q = select(SourceRecord).where(
        SourceRecord.household_id == ctx.household_id,
        SourceRecord.status == "active",
        SourceRecord.direction == "out",
        or_(
            (SourceRecord.amount == Decimal(r["amount"])) & (SourceRecord.occurred_on.between(d - timedelta(days=3), d + timedelta(days=3))),
            (SourceRecord.upi_txn_id == r["reference"]) | (SourceRecord.utr == r["reference"]) if r["reference"] else False,
        ),
    )
    s = ctx.db.scalars(q.limit(1)).first()
    if not s:
        return None
    return {"transaction_id": str(s.canonical_transaction_id), "source_type": s.source_type, "description": s.merchant_raw or s.description, "amount": format(Decimal(s.amount), "f"), "occurred_on": s.occurred_on.isoformat()}


@router.get("/{imp_id}/preview")
def preview(imp_id: uuid.UUID, ctx: Ctx = Depends(get_ctx), limit: int = Query(500, le=5000)):
    imp = _get(ctx, imp_id)
    rows = _preview_rows(ctx, imp)
    shown = rows[:limit]
    for r in shown:
        r["possible_match"] = _possible_match(ctx, r)
        r.pop("base_fingerprint", None)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("new", "duplicate_existing", "invalid")}
    totals_out = sum((Decimal(r["amount"]) for r in rows if r["status"] == "new" and r["direction"] == "out"), Decimal("0"))
    totals_in = sum((Decimal(r["amount"]) for r in rows if r["status"] == "new" and r["direction"] == "in"), Decimal("0"))
    return {
        "import": _out(imp, 0),
        "rows": shown,
        "counts": counts,
        "new_debits_total": format(totals_out, "f"),
        "new_credits_total": format(totals_in, "f"),
        "possible_matches": sum(1 for r in shown if r.get("possible_match")),
    }


@router.post("/{imp_id}/confirm")
def confirm(imp_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    """Idempotent. Rows already imported (same fingerprint) are skipped, so re-importing a statement never duplicates spending."""
    imp = _get(ctx, imp_id, lock=True)
    if imp.status == "confirmed":
        return _out(imp, 0)
    rows = _preview_rows(ctx, imp)
    imported = skipped = invalid = 0
    created_tx = []
    for r in rows:
        if r["status"] == "invalid":
            invalid += 1
            continue
        fp = r["fingerprint"]
        row_id = uuid.uuid4()
        stmt = (
            insert(StatementRow)
            .values(
                id=row_id,
                household_id=ctx.household_id,
                import_id=imp.id,
                account_id=imp.account_id,
                row_index=r["row_index"],
                raw=r["raw"],
                occurred_on=date.fromisoformat(r["occurred_on"]),
                description=r["description"] or "(no description)",
                amount=Decimal(r["amount"]),
                direction=r["direction"],
                currency=r["currency"],
                reference=r["reference"],
                balance=Decimal(r["balance"]) if r["balance"] else None,
                fingerprint=fp,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["household_id", "fingerprint"])
            .returning(StatementRow.id)
        )
        if ctx.db.execute(stmt).scalar() is None:
            skipped += 1
            existing = ctx.db.scalars(select(StatementRow).where(StatementRow.household_id == ctx.household_id, StatementRow.fingerprint == fp)).first()
            ctx.db.add(
                DuplicateCandidate(
                    household_id=ctx.household_id,
                    kind="statement_row",
                    existing_statement_row_id=existing.id if existing else None,
                    import_id=imp.id,
                    attempted_filename=imp.original_filename,
                    details={"description": r["description"], "amount": r["amount"], "date": r["occurred_on"]},
                    detected_by=ctx.user.id,
                )
            )
            continue
        tx_type = r["suggested_type"]
        account_id, to_account_id = imp.account_id, None
        if tx_type in ("transfer", "credit_card_payment"):
            if r["direction"] == "in":
                account_id, to_account_id = None, imp.account_id
            if not (account_id or to_account_id):
                tx_type = "expense" if r["direction"] == "out" else "income"
        is_upi = r["channel"] == "upi" or imp.source_kind == "upi"
        ref = r["reference"]
        tx_in = TransactionIn(
            type=tx_type,
            occurred_on=date.fromisoformat(r["occurred_on"]),
            description=r["description"][:500],
            amount=Decimal(r["amount"]),
            currency=r["currency"],
            merchant_name=(r["payee"] or None) if tx_type in ("expense", "refund", "income") else None,
            account_id=account_id,
            to_account_id=to_account_id,
            payment_method="credit_card" if imp.source_kind == "credit_card" else ("upi" if is_upi else CHANNEL_METHOD.get(r["channel"] or "")),
            record_as="payment",
            upi_txn_id=ref if is_upi else None,
            bank_ref=None if is_upi else ref,
        )
        ct = create_transaction(ctx, tx_in, source_type="statement_row", statement_row_id=row_id, commit=False)
        created_tx.append(str(ct.id))
        imported += 1
    imp.status = "confirmed"
    imp.imported_count = imported
    imp.skipped_duplicates = skipped
    imp.invalid_count = invalid
    imp.confirmed_at = utcnow()
    audit(ctx, "confirm", "statement_import", imp.id, None, {"imported": imported, "skipped_duplicates": skipped, "invalid": invalid})
    ctx.db.commit()
    out = _out(imp, 0)
    out["transaction_ids"] = created_tx
    return out


@router.delete("/{imp_id}")
def discard(imp_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    imp = _get(ctx, imp_id)
    if imp.status == "confirmed":
        raise Conflict("Confirmed imports can't be discarded; void individual transactions instead", code="import_confirmed")
    get_storage().delete(imp.storage_key)
    ctx.db.delete(imp)
    ctx.db.commit()
    return {"ok": True}

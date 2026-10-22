import uuid
from datetime import date, datetime, time
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import Ctx, get_ctx, writer_ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import sign_download, verify_download
from app.core.storage import get_storage
from app.models import Document, DocumentProcessingJob, ExtractedDocument, SourceRecord
from app.modules.common import Money, OptMoney, Schema, audit
from app.modules.documents.parser import validate as validate_fields
from app.modules.documents.service import upload_document
from app.modules.ledger.service import LineItemIn, TransactionIn, create_transaction, name_lookup, serialize_transaction

router = APIRouter(tags=["documents"])


def _doc_out(db, d: Document, detail: bool = False) -> dict:
    out = {
        "id": str(d.id),
        "filename": d.original_filename,
        "content_type": d.content_type,
        "size_bytes": d.size_bytes,
        "sha256": d.sha256,
        "status": d.status,
        "doc_kind": d.doc_kind,
        "page_count": d.page_count,
        "error_message": d.error_message,
        "created_at": d.created_at.isoformat(),
    }
    ext = db.scalars(select(ExtractedDocument).where(ExtractedDocument.document_id == d.id)).first()
    if ext:
        out["overall_confidence"] = float(ext.overall_confidence)
        out["merchant"] = (ext.fields.get("merchant_name") or {}).get("value")
        out["total"] = (ext.fields.get("total") or {}).get("value")
        out["date"] = (ext.fields.get("date") or {}).get("value")
        out["transaction_id"] = str(ext.transaction_id) if ext.transaction_id else None
        if detail:
            out["extraction"] = {
                "method": ext.method,
                "fields": ext.fields,
                "line_items": ext.line_items,
                "validation": ext.validation,
                "suggested_category_id": str(ext.suggested_category_id) if ext.suggested_category_id else None,
                "category_reasons": ext.category_reasons or [],
                "suggested_merchant_id": str(ext.suggested_merchant_id) if ext.suggested_merchant_id else None,
                "raw_text": ext.raw_text[:20000],
            }
    if detail:
        jobs = db.scalars(select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == d.id).order_by(DocumentProcessingJob.created_at)).all()
        out["jobs"] = [{"status": j.status, "attempts": j.attempts, "last_error": j.last_error, "created_at": j.created_at.isoformat()} for j in jobs]
    return out


def _get(ctx: Ctx, doc_id: uuid.UUID) -> Document:
    d = ctx.db.get(Document, doc_id)
    if d is None or d.household_id != ctx.household_id:
        raise NotFound("Document not found")
    return d


def _enqueue(db, doc: Document) -> None:
    from app.tasks import process_document_task

    job = db.scalars(select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == doc.id, DocumentProcessingJob.status == "queued").order_by(DocumentProcessingJob.created_at.desc())).first()
    process_document_task.delay(str(doc.id), str(job.id) if job else None)


@router.post("/documents", status_code=201)
async def upload(file: UploadFile = File(...), doc_kind: str | None = Form(default=None), ctx: Ctx = Depends(writer_ctx)):
    data = await file.read(get_settings().max_upload_bytes + 1)
    doc = upload_document(ctx, file.filename or "upload", data, doc_kind)
    _enqueue(ctx.db, doc)
    ctx.db.expire_all()
    return _doc_out(ctx.db, ctx.db.get(Document, doc.id))


@router.get("/documents")
def list_documents(ctx: Ctx = Depends(get_ctx), status: str | None = None, page: int = 1, page_size: int = Query(50, le=200)):
    q = select(Document).where(Document.household_id == ctx.household_id)
    if status:
        q = q.where(Document.status.in_(status.split(",")))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_doc_out(ctx.db, d) for d in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/documents/{doc_id}")
def get_document(doc_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return _doc_out(ctx.db, _get(ctx, doc_id), detail=True)


@router.get("/documents/{doc_id}/download-link")
def download_link(doc_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    d = _get(ctx, doc_id)
    s = get_settings()
    token = sign_download(str(d.id), str(ctx.household_id), s.download_link_seconds)
    return {"url": f"{s.api_prefix}/files/{token}", "expires_in": s.download_link_seconds}


@router.get("/files/{token}", include_in_schema=False)
def serve_file(token: str, db=Depends(get_db)):
    parsed = verify_download(token)
    if not parsed:
        raise NotFound("Link expired or invalid")
    doc_id, hid = parsed
    d = db.get(Document, uuid.UUID(doc_id))
    if d is None or str(d.household_id) != hid:
        raise NotFound("Link expired or invalid")
    data = get_storage().get(d.storage_key)
    safe_name = "".join(c for c in d.original_filename if c.isalnum() or c in "._- ")[:100] or "document"
    return Response(
        data,
        media_type=d.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            # Same-origin framing lets the review screen preview the file; scripts are never allowed.
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; object-src 'self'; frame-ancestors 'self'"
            + ("" if d.content_type == "application/pdf" else "; sandbox"),
        },
    )


@router.post("/documents/{doc_id}/reprocess")
def reprocess(doc_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    d = _get(ctx, doc_id)
    if d.status in ("confirmed", "archived"):
        raise Conflict("Confirmed documents cannot be reprocessed", code="document_confirmed")
    d.status = "queued"
    ctx.db.add(DocumentProcessingJob(household_id=ctx.household_id, document_id=d.id, job_type="extract", status="queued"))
    audit(ctx, "reprocess", "document", d.id)
    ctx.db.commit()
    _enqueue(ctx.db, d)
    ctx.db.expire_all()
    return _doc_out(ctx.db, _get(ctx, doc_id), detail=True)


class ExtractionUpdate(Schema):
    fields: dict[str, object]
    line_items: list[dict] = Field(default_factory=list, max_length=500)


@router.put("/documents/{doc_id}/extraction")
def save_extraction(doc_id: uuid.UUID, body: ExtractionUpdate, ctx: Ctx = Depends(writer_ctx)):
    """Saves the user's corrections (values entered by the user get confidence 1.0) and re-validates."""
    d = _get(ctx, doc_id)
    if d.status not in ("needs_review", "failed"):
        raise Conflict(f"A {d.status} document cannot be edited", code="not_editable")
    ext = ctx.db.scalars(select(ExtractedDocument).where(ExtractedDocument.document_id == d.id)).first()
    if ext is None:
        ext = ExtractedDocument(household_id=ctx.household_id, document_id=d.id, method="manual")
        ctx.db.add(ext)
    fields = dict(ext.fields or {})
    for k, v in body.fields.items():
        prev = fields.get(k) or {}
        if prev.get("value") != v:
            fields[k] = {"value": v if v not in ("", None) else None, "confidence": 1.0 if v not in ("", None) else 0.0, "edited": True}
    ext.fields = fields
    ext.line_items = body.line_items
    ext.validation = validate_fields(fields, body.line_items)
    if d.status == "failed":
        d.status = "needs_review"
    audit(ctx, "edit_extraction", "document", d.id)
    ctx.db.commit()
    return _doc_out(ctx.db, d, detail=True)


class ConfirmDocumentIn(Schema):
    merchant_name: str = Field(min_length=1, max_length=200)
    occurred_on: date
    occurred_time: time | None = None
    amount: Money
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    category_id: uuid.UUID | None = None
    payment_method: str | None = None
    account_id: uuid.UUID | None = None
    invoice_number: str | None = None
    payment_reference: str | None = None
    order_id: str | None = None
    description: str = ""
    notes: str = ""
    doc_kind: str = Field(default="receipt", pattern="^(receipt|invoice|upi_screenshot)$")
    line_items: list[LineItemIn] = Field(default_factory=list, max_length=500)
    discount: OptMoney = None
    tax: OptMoney = None


@router.post("/documents/{doc_id}/confirm")
def confirm(doc_id: uuid.UUID, body: ConfirmDocumentIn, ctx: Ctx = Depends(writer_ctx)):
    d = ctx.db.scalars(select(Document).where(Document.id == doc_id).with_for_update()).first()
    if d is None or d.household_id != ctx.household_id:
        raise NotFound("Document not found")
    existing = ctx.db.scalars(select(SourceRecord).where(SourceRecord.document_id == d.id)).first()
    if existing:  # idempotent: one document -> one source record, ever
        from app.models import CanonicalTransaction

        ct = ctx.db.get(CanonicalTransaction, existing.canonical_transaction_id)
        return {"document": _doc_out(ctx.db, d), "transaction": serialize_transaction(ctx.db, ct, detail=True, names=name_lookup(ctx.db, ctx.household_id, [ct]))}
    if d.status not in ("needs_review", "failed"):
        raise Conflict(f"Only documents awaiting review can be confirmed (this one is {d.status})", code="not_confirmable")
    if body.amount <= 0:
        raise ValidationFailed("Amount must be greater than zero")
    ext = ctx.db.scalars(select(ExtractedDocument).where(ExtractedDocument.document_id == d.id)).first()
    if ext and (ext.fields.get("payment_status") or {}).get("value") == "not_completed" and body.doc_kind == "upi_screenshot":
        raise ValidationFailed("The screenshot shows a failed, pending or reversed payment; it can't be recorded as a completed expense.", code="payment_not_completed")
    occurred_at = datetime.combine(body.occurred_on, body.occurred_time) if body.occurred_time else None
    is_payment = body.doc_kind == "upi_screenshot"
    ref = (body.payment_reference or "").strip().upper() or None
    extra_notes = []
    if body.discount is not None:
        extra_notes.append(f"Discount {body.discount}")
    if body.tax is not None:
        extra_notes.append(f"Tax {body.tax}")
    tx_in = TransactionIn(
        type="expense",
        occurred_on=body.occurred_on,
        occurred_at=occurred_at,
        description=body.description or body.merchant_name,
        amount=body.amount,
        currency=body.currency,
        category_id=body.category_id,
        merchant_name=body.merchant_name,
        account_id=body.account_id,
        payment_method=body.payment_method or ("upi" if is_payment else None),
        notes="\n".join(filter(None, [body.notes, "; ".join(extra_notes)])),
        line_items=body.line_items,
        record_as="payment" if is_payment else "bill",
        upi_txn_id=ref,
        invoice_number=(body.invoice_number or "").strip().upper() or None,
        order_id=(body.order_id or "").strip().upper() or None,
    )
    ct = create_transaction(
        ctx,
        tx_in,
        source_type=body.doc_kind,
        document_id=d.id,
        category_source="confirmed" if body.category_id else None,
        commit=False,
        context_text=ext.raw_text if ext else "",
    )
    d.status = "confirmed"
    d.doc_kind = body.doc_kind
    if ext is None:
        ext = ExtractedDocument(household_id=ctx.household_id, document_id=d.id, method="manual")
        ctx.db.add(ext)
    ext.transaction_id = ct.id
    # Keep the document list consistent with what the user confirmed (extracted values stay in the audit trail).
    confirmed = {"merchant_name": body.merchant_name, "date": body.occurred_on.isoformat(), "total": format(Decimal(ct.amount), "f")}
    fields = dict(ext.fields or {})
    for k, v in confirmed.items():
        prev = fields.get(k) or {}
        if prev.get("value") != v:
            fields[k] = {**prev, "value": v, "confidence": 1.0, "edited": True, "extracted_value": prev.get("value")}
    ext.fields = fields
    audit(ctx, "confirm", "document", d.id, None, {"transaction_id": str(ct.id), "amount": format(Decimal(ct.amount), "f")})
    ctx.db.commit()
    return {"document": _doc_out(ctx.db, d), "transaction": serialize_transaction(ctx.db, ct, detail=True, names=name_lookup(ctx.db, ctx.household_id, [ct]))}


@router.post("/documents/{doc_id}/archive")
def archive(doc_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    d = _get(ctx, doc_id)
    d.status = "archived"
    audit(ctx, "archive", "document", d.id)
    ctx.db.commit()
    return _doc_out(ctx.db, d)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    d = _get(ctx, doc_id)
    if ctx.db.scalars(select(SourceRecord).where(SourceRecord.document_id == d.id)).first():
        raise Conflict("This document backs a confirmed transaction. Archive it instead, or void the transaction first.", code="document_in_use")
    get_storage().delete(d.storage_key)
    audit(ctx, "delete", "document", d.id, {"filename": d.original_filename, "sha256": d.sha256}, None)
    ctx.db.delete(d)
    ctx.db.commit()
    return {"ok": True}

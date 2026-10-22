import hashlib
import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import Ctx
from app.core.errors import Conflict
from app.core.storage import get_storage, new_key
from app.models import Document, DocumentProcessingJob, DuplicateCandidate, ExtractedDocument, Household, SourceRecord
from app.modules.categories.service import categorize
from app.modules.common import audit
from app.modules.documents.ocr import OcrUnavailable, extract_text
from app.modules.documents.parser import parse_document
from app.modules.documents.validation import validate_document
from app.modules.merchants.service import find_merchant
from app.modules.notifications.service import notify

log = logging.getLogger("smartspend.documents")

SUFFIX = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def upload_document(ctx: Ctx, filename: str, data: bytes, doc_kind_hint: str | None = None) -> Document:
    ctype, pages = validate_document(filename, data)
    digest = hashlib.sha256(data).hexdigest()
    existing = ctx.db.scalars(select(Document).where(Document.household_id == ctx.household_id, Document.sha256 == digest)).first()
    if existing:
        _record_duplicate(ctx, existing, filename)
        raise Conflict(
            f"This exact file was already uploaded as '{existing.original_filename}'.",
            code="duplicate_document",
            details={"existing_document_id": str(existing.id), "status": existing.status},
        )
    key = new_key(ctx.household_id, SUFFIX[ctype])
    get_storage().put(key, data, ctype)
    doc = Document(
        household_id=ctx.household_id,
        uploaded_by=ctx.user.id,
        original_filename=filename[:255],
        content_type=ctype,
        size_bytes=len(data),
        sha256=digest,
        storage_key=key,
        status="queued",
        doc_kind=doc_kind_hint if doc_kind_hint in ("receipt", "invoice", "upi_screenshot") else "receipt",
        page_count=pages,
    )
    ctx.db.add(doc)
    try:
        ctx.db.flush()
    except IntegrityError:
        # A concurrent upload of the same file won the race.
        ctx.db.rollback()
        get_storage().delete(key)
        existing = ctx.db.scalars(select(Document).where(Document.household_id == ctx.household_id, Document.sha256 == digest)).one()
        _record_duplicate(ctx, existing, filename)
        raise Conflict("This exact file was already uploaded.", code="duplicate_document", details={"existing_document_id": str(existing.id)})
    job = DocumentProcessingJob(household_id=ctx.household_id, document_id=doc.id, job_type="extract", status="queued")
    ctx.db.add(job)
    audit(ctx, "upload", "document", doc.id, None, {"filename": doc.original_filename, "sha256": digest, "size": len(data)})
    ctx.db.commit()
    return doc


def _record_duplicate(ctx: Ctx, existing: Document, filename: str) -> None:
    ctx.db.add(
        DuplicateCandidate(
            household_id=ctx.household_id,
            kind="document_hash",
            existing_document_id=existing.id,
            attempted_filename=filename[:255],
            details={"sha256": existing.sha256},
            detected_by=ctx.user.id,
        )
    )
    ctx.db.commit()


def process_document(db: Session, document_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
    """Idempotent: re-running on a processed document is a no-op. Returns the resulting status."""
    doc = db.scalars(select(Document).where(Document.id == document_id).with_for_update()).first()
    if doc is None:
        return "missing"
    if doc.status in ("needs_review", "confirmed", "archived"):
        return doc.status
    job = db.get(DocumentProcessingJob, job_id) if job_id else db.scalars(
        select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == doc.id).order_by(DocumentProcessingJob.created_at.desc())
    ).first()
    if job is None:
        job = DocumentProcessingJob(household_id=doc.household_id, document_id=doc.id, job_type="extract")
        db.add(job)
    job.status = "running"
    job.attempts += 1
    job.started_at = utcnow()
    doc.status = "processing"
    db.commit()

    household = db.get(Household, doc.household_id)
    try:
        data = get_storage().get(doc.storage_key)
        try:
            text, method = extract_text(data, doc.content_type)
            parsed = parse_document(text)
            if method == "ocr":
                text, parsed = _second_chance(data, doc.content_type, text, parsed)
        except OcrUnavailable as exc:
            text, method = "", "none"
            parsed = {
                "kind": doc.doc_kind,
                "fields": {},
                "line_items": [],
                "validation": [{"level": "error", "code": "ocr_unavailable", "message": f"{exc} Enter the details manually from the document preview."}],
                "overall_confidence": 0.0,
            }
        # Optional, opt-in AI fills only empty fields; anything it suggests is verified against the text.
        from app.modules.ai.provider import suggest_missing_fields

        ai = suggest_missing_fields(household, text, parsed["fields"]) if text else {}
        if ai:
            parsed["fields"].update(ai)
            filled = {"total_missing": "total", "date_missing": "date", "merchant_missing": "merchant_name"}
            parsed["validation"] = [i for i in parsed["validation"] if filled.get(i["code"]) not in ai]
            parsed["validation"].append({"level": "info", "code": "ai_suggestions", "message": f"AI suggested {', '.join(sorted(ai))}. Please verify these against the document."})
        ext = db.scalars(select(ExtractedDocument).where(ExtractedDocument.document_id == doc.id)).first() or ExtractedDocument(household_id=doc.household_id, document_id=doc.id, method=method)
        ext.method = method
        ext.raw_text = text[:200_000]
        ext.fields = parsed["fields"]
        ext.line_items = parsed["line_items"]
        ext.validation = parsed["validation"]
        ext.overall_confidence = Decimal(str(parsed["overall_confidence"]))
        merchant_name = (parsed["fields"].get("merchant_name") or {}).get("value")
        merchant = find_merchant(db, doc.household_id, merchant_name) if merchant_name else None
        if merchant is not None:
            ext.suggested_merchant_id = merchant.id
            parsed["fields"]["merchant_name"]["confidence"] = max(parsed["fields"]["merchant_name"]["confidence"], 0.9)
            ext.fields = dict(parsed["fields"])
        cat = categorize(
            db,
            doc.household_id,
            description=merchant_name or "",
            merchant_name=merchant_name or "",
            merchant_id=merchant.id if merchant else None,
            item_names=[i["name"] for i in parsed["line_items"]],
            document_text=text,  # utility bills describe themselves in the body ("Water Charge", "kWh")
        )
        ext.suggested_category_id = cat["category_id"]
        ext.category_reasons = cat.get("reasons") or []
        _flag_possible_duplicates(db, doc, ext)
        db.add(ext)
        if parsed["kind"] in ("receipt", "invoice", "upi_screenshot") and doc.doc_kind == "receipt":
            doc.doc_kind = parsed["kind"]
        doc.status = "needs_review"
        doc.error_message = ""
        job.status = "succeeded"
        job.finished_at = utcnow()
        db.commit()
        if any(i["code"] == "ocr_unavailable" for i in parsed["validation"]):
            notify(db, household.id, "document_needs_manual_entry", f"Enter details for {doc.original_filename}", "OCR is not available for this file; open it to enter the details manually.", f"/upload?doc={doc.id}", key=f"doc-ocr:{doc.id}", severity="warning")
        return doc.status
    except Exception as exc:  # bounded retries, then fail visibly
        db.rollback()
        log.exception("Document processing failed")
        job = db.get(DocumentProcessingJob, job.id)
        doc = db.get(Document, doc.id)
        job.last_error = str(exc)[:2000]
        job.finished_at = utcnow()
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            doc.status = "failed"
            doc.error_message = "Processing failed after several attempts. You can retry or enter the details manually."
            db.commit()
            notify(db, doc.household_id, "document_failed", f"Could not process {doc.original_filename}", doc.error_message, f"/upload?doc={doc.id}", key=f"doc-failed:{doc.id}", severity="warning")
        else:
            job.status = "queued"
            doc.status = "queued"
            db.commit()
            raise
        return doc.status


SECOND_CHANCE_FIELDS = ("total", "date", "currency", "merchant_name", "invoice_number", "payment_reference", "subtotal", "tax", "discount")


def _second_chance(data: bytes, content_type: str, text: str, parsed: dict) -> tuple[str, dict]:
    """Photos of curled or folded bills: if the total or date is missing, re-read the image straightened to
    the angles its text actually runs at, and fill only the fields that are still empty."""
    from app.modules.documents.ocr import retry_texts
    from app.modules.documents.parser import validate

    fields = parsed["fields"]
    if (fields.get("total") or {}).get("value") and (fields.get("date") or {}).get("value"):
        return text, parsed
    filled = []
    for extra in retry_texts(data, content_type):
        retry = parse_document(extra)
        for key in SECOND_CHANCE_FIELDS:
            if not (fields.get(key) or {}).get("value") and (retry["fields"].get(key) or {}).get("value"):
                fields[key] = {**retry["fields"][key], "source": "rotated_ocr"}
                filled.append(key)
        if not parsed["line_items"] and retry["line_items"]:
            parsed["line_items"] = retry["line_items"]
        text = f"{text}\n\n--- re-read with the image straightened ---\n{extra}"
        if (fields.get("total") or {}).get("value") and (fields.get("date") or {}).get("value"):
            break
    if filled:
        parsed["validation"] = validate(fields, parsed["line_items"]) + [
            {"level": "info", "code": "rotated_ocr", "message": f"The photo is curled or tilted; {', '.join(sorted(set(filled)))} were read from a straightened copy. Please check them."}
        ]
    return text, parsed


def _flag_possible_duplicates(db: Session, doc: Document, ext: ExtractedDocument) -> None:
    inv = (ext.fields.get("invoice_number") or {}).get("value")
    if not inv:
        return
    clash = db.scalars(
        select(SourceRecord).where(SourceRecord.household_id == doc.household_id, SourceRecord.invoice_number == inv, SourceRecord.status == "active")
    ).first()
    if clash:
        ext.validation = list(ext.validation) + [
            {
                "level": "warning",
                "code": "possible_duplicate_bill",
                "message": f"A bill with invoice number {inv} is already recorded. Confirming will create a duplicate suggestion for review.",
                "transaction_id": str(clash.canonical_transaction_id),
            }
        ]

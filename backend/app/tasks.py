"""Celery task entry points. Every task is idempotent (it re-reads state under a row lock and exits if the
work is already done) and retries are bounded with exponential backoff."""
import logging
import uuid

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.db import SessionLocal

log = logging.getLogger("smartspend.tasks")


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10, acks_late=True)
def process_document_task(self, document_id: str, job_id: str | None = None):
    from app.modules.documents.service import process_document

    with SessionLocal() as db:
        try:
            return process_document(db, uuid.UUID(document_id), uuid.UUID(job_id) if job_id else None)
        except Exception as exc:
            if celery_app.conf.task_always_eager:
                # Inline mode: retry immediately (process_document counts attempts and fails after max_attempts).
                if self.request.retries < self.max_retries:
                    return process_document_task.run(document_id, job_id)
                return "failed"
            raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))


@celery_app.task
def run_all_notification_checks():
    from app.models import Household
    from app.modules.notifications.service import run_checks

    with SessionLocal() as db:
        total = 0
        for h in db.scalars(select(Household)).all():
            try:
                total += run_checks(db, h)
            except Exception:
                log.exception("notification checks failed for %s", h.id)
                db.rollback()
        return total


@celery_app.task(bind=True, max_retries=3)
def regenerate_candidates_task(self, household_id: str):
    from app.models import Household, SourceRecord
    from app.modules.reconciliation import engine
    from app.modules.reconciliation.state import recompute_for_sources

    with SessionLocal() as db:
        h = db.get(Household, uuid.UUID(household_id))
        if h is None:
            return 0
        ids = []
        for s in db.scalars(select(SourceRecord).where(SourceRecord.household_id == h.id, SourceRecord.status == "active")).all():
            engine.generate_candidates(db, h, s)
            ids.append(s.id)
        recompute_for_sources(db, ids)
        db.commit()
        return len(ids)

"""Extension points for future data sources. None of these is active: each reports `configured: false` until a
real connector is implemented and configured. Connectors must feed data through the same paths as manual
uploads (documents pipeline, statement import) so deduplication and reconciliation apply unchanged."""
from typing import Protocol

from fastapi import APIRouter, Depends

from app.core.deps import Ctx, get_ctx

router = APIRouter(prefix="/integrations", tags=["integrations"])


class StatementConnector(Protocol):
    """Bank / card / UPI / wallet providers (e.g. an Account Aggregator). Returns statement files or rows that are
    imported via the statement import pipeline (fingerprinting makes re-sync idempotent)."""

    key: str

    def fetch_statements(self, household_id, account_id, since) -> list[tuple[str, bytes]]: ...


class ReceiptInbox(Protocol):
    """Email receipt ingestion. Returns (filename, bytes) attachments for the documents pipeline (hash-deduplicated)."""

    key: str

    def fetch_new_receipts(self, household_id) -> list[tuple[str, bytes]]: ...


class CloudFolder(Protocol):
    """Cloud storage folder watch (Drive, Dropbox, ...). Same contract as ReceiptInbox."""

    key: str

    def list_new_files(self, household_id) -> list[tuple[str, bytes]]: ...


AVAILABLE = [
    {"key": "account_aggregator", "kind": "bank", "name": "Bank account aggregation", "interface": "StatementConnector"},
    {"key": "email_receipts", "kind": "email", "name": "Email receipt forwarding", "interface": "ReceiptInbox"},
    {"key": "cloud_folder", "kind": "storage", "name": "Cloud storage folder", "interface": "CloudFolder"},
    {"key": "upi_app_export", "kind": "payments", "name": "UPI app automatic export", "interface": "StatementConnector"},
]
REGISTRY: dict[str, object] = {}  # implemented connectors register here


@router.get("")
def list_integrations(ctx: Ctx = Depends(get_ctx)):
    return [
        {**i, "configured": i["key"] in REGISTRY, "status": "active" if i["key"] in REGISTRY else "not_configured"}
        for i in AVAILABLE
    ]

"""Upload validation: size, magic-byte content sniffing, structural checks and optional ClamAV scanning."""
import io
import logging
import socket
import struct

from PIL import Image

from app.core.config import get_settings
from app.core.errors import AppError, ValidationFailed

log = logging.getLogger("smartspend.uploads")

Image.MAX_IMAGE_PIXELS = 60_000_000  # decompression-bomb guard

DOC_TYPES = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}
STATEMENT_TYPES = {
    "text/csv": (".csv", ".txt"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx",),
    "application/pdf": (".pdf",),
}


def sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    return None


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def validate_document(filename: str, data: bytes) -> tuple[str, int | None]:
    """Returns (content_type, page_count). Raises ValidationFailed for anything unexpected."""
    s = get_settings()
    if not data:
        raise ValidationFailed("The file is empty", code="empty_file")
    if len(data) > s.max_upload_bytes:
        raise ValidationFailed(f"File is larger than {s.max_upload_bytes // (1024 * 1024)} MB", code="file_too_large")
    ctype = sniff(data)
    if ctype not in DOC_TYPES:
        raise ValidationFailed("Unsupported file type. Upload a PDF, JPG, PNG or WebP.", code="unsupported_type")
    if _ext(filename) not in DOC_TYPES[ctype]:
        raise ValidationFailed("The file extension does not match its contents", code="extension_mismatch")
    pages = None
    if ctype == "application/pdf":
        import pymupdf

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception:
            raise ValidationFailed("The PDF could not be read (it may be corrupted)", code="corrupt_pdf")
        if doc.needs_pass:
            raise ValidationFailed("Password-protected PDFs are not supported. Remove the password and upload again.", code="encrypted_pdf")
        pages = doc.page_count
        if pages > 50:
            raise ValidationFailed("PDF has more than 50 pages", code="too_many_pages")
    else:
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except Exception:
            raise ValidationFailed("The image could not be read (it may be corrupted)", code="corrupt_image")
    scan_for_malware(data)
    return ctype, pages


def validate_statement(filename: str, data: bytes) -> str:
    s = get_settings()
    if not data:
        raise ValidationFailed("The file is empty", code="empty_file")
    if len(data) > s.max_upload_bytes:
        raise ValidationFailed("File is too large", code="file_too_large")
    ext = _ext(filename)
    sniffed = sniff(data)
    if ext == ".pdf" and sniffed == "application/pdf":
        fmt = "pdf"
    elif ext == ".xlsx" and sniffed == "application/zip":
        fmt = "xlsx"
    elif ext in (".csv", ".txt") and sniffed is None:
        try:
            data[:4096].decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                data[:4096].decode("latin-1")
            except Exception:
                raise ValidationFailed("CSV must be text", code="unsupported_type")
        fmt = "csv"
    else:
        raise ValidationFailed("Upload a CSV, XLSX or PDF statement", code="unsupported_type")
    scan_for_malware(data)
    return fmt


class MalwareDetected(AppError):
    status_code = 422
    code = "malware_detected"


def scan_for_malware(data: bytes) -> None:
    s = get_settings()
    if s.malware_scanner != "clamav":
        return
    try:
        with socket.create_connection((s.clamav_host, s.clamav_port), timeout=10) as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), 8192):
                chunk = data[i : i + 8192]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = sock.recv(4096).decode(errors="replace")
    except OSError as exc:
        log.error("ClamAV unreachable: %s", exc)
        raise AppError("The malware scanner is unavailable; please try again later.", code="scanner_unavailable", status_code=503)
    if "FOUND" in reply:
        raise MalwareDetected("The file was rejected by the malware scanner.")

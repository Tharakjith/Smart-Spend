"""Optional AI assistance. Off by default and strictly advisory.

Guarantees:
* Runs only when the server sets AI_PROVIDER=anthropic and AI_ALLOW_DOCUMENT_SHARING=true AND the household
  has opted in (households.ai_opt_in). Otherwise every function returns None without network access.
* Only extracted text is sent (never the original image or PDF), and only what the task needs.
* AI output never merges, links or confirms anything: it fills empty review fields, marked source="ai",
  and the user still reviews and confirms. Values that do not literally appear in the document text are
  discarded, so a model cannot introduce figures that are not on the receipt.
"""
import json
import logging
import re
from decimal import Decimal, InvalidOperation

from app.core.config import get_settings

log = logging.getLogger("smartspend.ai")

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant_name": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "total": {"type": ["string", "null"], "description": "Grand total exactly as printed, digits and decimal point only"},
        "currency": {"type": ["string", "null"], "description": "ISO 4217 code"},
        "invoice_number": {"type": ["string", "null"]},
        "payment_reference": {"type": ["string", "null"]},
    },
    "required": ["merchant_name", "date", "total", "currency", "invoice_number", "payment_reference"],
    "additionalProperties": False,
}

EXTRACTION_SYSTEM = (
    "You read text extracted from receipts, invoices and payment screenshots and return the requested fields as JSON. "
    "Copy values exactly as they appear in the text. If a field is not present in the text, return null for it - "
    "never estimate, compute or infer a value that is not written in the document. The total is the final amount payable."
)


def ai_enabled(household) -> bool:
    s = get_settings()
    return s.ai_provider == "anthropic" and s.ai_allow_document_sharing and bool(household is not None and household.ai_opt_in)


def _client():
    import anthropic

    s = get_settings()
    return anthropic.Anthropic(api_key=s.anthropic_api_key or None, max_retries=2, timeout=60.0)


def _call_json(system: str, user_text: str, schema: dict, effort: str) -> dict | None:
    import anthropic

    s = get_settings()
    try:
        response = _client().beta.messages.create(
            model=s.ai_model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # Refusal fallbacks: on a policy decline the API retries on a fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        log.warning("AI provider rate limited; continuing without AI suggestions")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("AI provider error %s; continuing without AI suggestions", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("AI provider unreachable; continuing without AI suggestions")
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _appears_in(value: str, raw_text: str) -> bool:
    """A suggested value is kept only if it is literally present in the document text."""
    norm_text = re.sub(r"\s+", " ", raw_text).lower()
    v = re.sub(r"\s+", " ", value).strip().lower()
    if not v:
        return False
    if v in norm_text:
        return True
    try:  # amounts may be printed with thousands separators, e.g. 1,250.00
        d = Decimal(v.replace(",", ""))
        for m in re.findall(r"\d[\d,]*\.?\d*", raw_text):
            try:
                if Decimal(m.replace(",", "")) == d:
                    return True
            except InvalidOperation:
                continue
    except InvalidOperation:
        pass
    return False


def suggest_missing_fields(household, raw_text: str, fields: dict) -> dict:
    """Returns {field: {"value", "confidence", "source": "ai"}} only for fields that are currently empty."""
    if not ai_enabled(household) or not raw_text.strip():
        return {}
    wanted = [k for k in ("merchant_name", "date", "total", "currency", "invoice_number", "payment_reference") if not (fields.get(k) or {}).get("value")]
    if not wanted:
        return {}
    result = _call_json(EXTRACTION_SYSTEM, f"Document text:\n<document>\n{raw_text[:30000]}\n</document>", EXTRACTION_SCHEMA, effort="medium")
    if not result:
        return {}
    out = {}
    for key in wanted:
        value = result.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if key == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                continue  # dates are reformatted, so they cannot be checked literally; keep only well-formed ones
        elif key == "currency":
            if not re.fullmatch(r"[A-Z]{3}", value):
                continue
        elif not _appears_in(value, raw_text):
            log.info("Discarded AI suggestion for %s: not present in document text", key)
            continue
        out[key] = {"value": value.strip(), "confidence": 0.5, "source": "ai"}
    return out


def suggest_category(household, description: str, merchant: str, category_names: list[str]) -> str | None:
    """Picks one existing category name for an uncategorised transaction, or None."""
    if not ai_enabled(household) or not category_names:
        return None
    schema = {
        "type": "object",
        "properties": {"category": {"type": ["string", "null"], "enum": [*category_names, None]}},
        "required": ["category"],
        "additionalProperties": False,
    }
    result = _call_json(
        "You categorise personal expenses. Choose the single best category from the allowed list, or null if none clearly fits.",
        f"Merchant: {merchant or 'unknown'}\nDescription: {description or 'none'}",
        schema,
        effort="low",
    )
    name = (result or {}).get("category")
    return name if name in category_names else None

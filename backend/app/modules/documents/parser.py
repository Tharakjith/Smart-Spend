"""Deterministic receipt / invoice / UPI-screenshot parser.

Every field is returned as {"value": ..., "confidence": 0..1}. A field that is not present in the text is
returned with value None - nothing is guessed or fabricated. Validation issues explain inconsistencies.
"""
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

AMOUNT = r"(?:₹|rs\.?|inr)?\s*(-?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})|-?\d+(?:\.\d{1,2})?)"
AMOUNT_RE = re.compile(AMOUNT, re.I)
TRAILING_NUMS = re.compile(r"(-?\d[\d,]*\.?\d*)\s*$")

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

TOTAL_KEYS = [
    (r"grand\s*total", 1.0),
    (r"net\s*(?:amount|payable|total)", 0.95),
    (r"(?:total\s*)?amount\s*(?:payable|due|paid)", 0.95),
    (r"payable\s*(?:amt|amount)", 0.95),
    (r"bill\s*amount", 0.9),
    (r"invoice\s*(?:total|value|amount)", 0.9),
    (r"total\s*(?:amount|amt|rs|inr)?", 0.8),
]
SUBTOTAL_KEYS = r"sub\s*-?\s*total|total\s*before\s*tax|taxable\s*(?:value|amount)|gross\s*amount"
# Letter-only boundaries: OCR output glues rates on ("CGST2.5%").
TAX_KEYS = r"(?<![a-z])(?:cgst|sgst|igst|utgst|gst|vat|cess|tax)(?![a-z])"
DISCOUNT_KEYS = r"discount|you\s*saved|savings|coupon|offer"
CHARGE_KEYS = r"delivery|service\s*charge|packing|packaging|convenience\s*fee|handling|platform\s*fee|tip"
ROUND_KEYS = r"round\s*(?:off|ing)"
SKIP_ITEM_KEYS = re.compile(
    rf"({SUBTOTAL_KEYS}|{TAX_KEYS}|{DISCOUNT_KEYS}|{CHARGE_KEYS}|{ROUND_KEYS}|total|cash|change|balance|paid|upi|card|tender|gstin|invoice|bill\s*no|receipt|date|time|phone|ph[:.]|mob|thank|visit|items?\s*:|qty|hsn|amount|rate|price|mrp"
    # utility-bill tables (meter readings, consumption) are not purchased items
    rf"|reading|meter|consumer|no\.?\s*of\s*days|status)",
    re.I,
)
DATE_IN_LINE = re.compile(r"(?<!\d)\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}(?!\d)")
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|ml|l|ltr|litre|pcs|pc)\b", re.I)


def F(value, confidence: float) -> dict:
    return {"value": value, "confidence": round(confidence, 2) if value is not None else 0.0}


def dec(s: str | None) -> Decimal | None:
    if s is None:
        return None
    try:
        return Decimal(s.replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _amount_on(line: str) -> Decimal | None:
    nums = AMOUNT_RE.findall(line)
    return dec(nums[-1]) if nums else None


# Dates on a bill that are not the bill date. A line carrying one of these labels is a weaker candidate.
DATE_PENALTY = re.compile(r"due|disconn|valid|expir|prev|prv|last\s*p|reading|rdg|rd\s*dt|period|from|till|\bto\b|birth|dob", re.I)
DATE_BONUS = re.compile(r"bill\s*(?:no\.?\s*&\s*)?date|invoice\s*date|inv\s*date|txn\s*date|transaction\s*date|receipt\s*date|^\s*date\b|\bdate\s*[:\-]|\bdated\b", re.I)


def _date_candidates(line: str) -> list[tuple[tuple[int, int, int], float]]:
    t = line.lower()
    out = []
    # Digit-only boundaries: OCR often glues the next word on ("18/10/2026Time: 19:42").
    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", t):
        out.append(((int(m.group(1)), int(m.group(2)), int(m.group(3))), 0.95))
    # A 4-digit year may run straight into a time on printed timestamps ("02/10/202410:13:57").
    for m in re.finditer(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}(?=\d{1,2}:\d{2})|\d{4}(?!\d)|\d{2}(?!\d))", t):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        if mo > 12 and d <= 12:  # clearly month-first (US style)
            d, mo = mo, d
        out.append(((y, mo, d), 0.85))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]*([a-z]{3})[a-z]*[\s\-,]*(\d{2,4})\b", t):
        if m.group(2) in MONTHS:
            y = int(m.group(3))
            out.append(((y + 2000 if y < 100 else y, MONTHS[m.group(2)], int(m.group(1))), 0.9))
    for m in re.finditer(r"\b([a-z]{3})[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b", t):
        if m.group(1) in MONTHS:
            out.append(((int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))), 0.9))
    return out


def parse_date(text: str) -> tuple[date | None, float]:
    """The bill's own date. Bills also print due, disconnection and meter-reading dates, so a date labelled as the
    bill/invoice date wins; otherwise the earliest date not labelled as something else (the bill date always
    precedes its due date)."""
    labelled, neutral, other = [], [], []
    for line in text.splitlines():
        for ymd, conf in _date_candidates(line):
            try:
                dt = date(*ymd)
            except ValueError:
                continue
            if DATE_BONUS.search(line) and not DATE_PENALTY.search(line):
                labelled.append((dt, conf))
            elif DATE_PENALTY.search(line):
                other.append((dt, conf))
            else:
                neutral.append((dt, conf))
    if labelled:
        return labelled[0]
    if neutral:
        return min(neutral, key=lambda c: c[0])
    if other:
        return min(other, key=lambda c: c[0])
    return None, 0.0


def parse_time(text: str) -> tuple[time | None, float]:
    # Also accepts a time glued to a 4-digit year ("02/10/202410:13:57AM" -> 10:13:57).
    m = re.search(r"(?:(?<=\d{4})|(?<!\d))(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?\b", text, re.I)
    if not m:
        return None, 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    ap = (m.group(4) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    try:
        return time(h, mi, s), 0.85
    except ValueError:
        return None, 0.0


def detect_currency(text: str) -> tuple[str | None, float]:
    if re.search(r"₹|\brs\.?\s?\d|\binr\b|\brupees\b", text, re.I):
        return "INR", 0.95
    if re.search(r"\$\s?\d|\busd\b", text, re.I):
        return "USD", 0.9
    if re.search(r"€|\beur\b", text, re.I):
        return "EUR", 0.9
    if re.search(r"£|\bgbp\b", text, re.I):
        return "GBP", 0.9
    if re.search(r"\baed\b|\bdhs?\b", text, re.I):
        return "AED", 0.9
    return None, 0.0


def detect_payment_method(text: str) -> tuple[str | None, float]:
    t = text.lower()
    if re.search(r"\bupi\b|gpay|google\s*pay|phonepe|paytm|bhim", t):
        return "upi", 0.85
    if re.search(r"credit\s*card", t):
        return "credit_card", 0.8
    if re.search(r"debit\s*card", t):
        return "debit_card", 0.8
    if re.search(r"\bcard\b|visa|mastercard|rupay|amex", t):
        return "credit_card" if "credit" in t else "debit_card", 0.5
    if re.search(r"\bcash\b", t):
        return "cash", 0.75
    return None, 0.0


def find_reference(text: str) -> tuple[str | None, float]:
    m = re.search(r"(?:upi\s*(?:ref(?:erence)?|transaction)\s*(?:no\.?|id|number)?|utr(?:\s*no\.?)?|rrn|txn\s*id|transaction\s*id|ref\.?\s*no\.?)\s*[:#\-]?\s*([A-Za-z0-9]{8,30})", text, re.I)
    if m and any(ch.isdigit() for ch in m.group(1)):
        return m.group(1).upper(), 0.9
    return None, 0.0


def find_invoice_number(text: str) -> tuple[str | None, float]:
    # "b[il1|]{3}" also accepts OCR's usual misreads of "Bill" ("Bi11", "B1ll").
    # "Bill No & Date 183049449 - 22/12/2025" is a common utility-bill layout.
    m = re.search(r"(?:invoice|inv|b[il1|]{3}|receipt|order)\s*(?:no\.?|number|num|#|id)\s*(?:&\s*date)?\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{1,30})", text, re.I)
    if m and any(ch.isdigit() for ch in m.group(1)):
        return m.group(1).upper(), 0.85
    return None, 0.0


def find_order_id(text: str) -> tuple[str | None, float]:
    m = re.search(r"order\s*(?:id|no\.?|#)\s*[:#\-]?\s*([A-Za-z0-9\-]{5,40})", text, re.I)
    return (m.group(1).upper(), 0.85) if m and any(c.isdigit() for c in m.group(1)) else (None, 0.0)


def _labelled_amount(lines: list[str], pattern: str) -> tuple[Decimal | None, int | None]:
    for i, ln in enumerate(lines):
        if re.search(pattern, ln, re.I):
            amt = _amount_on(ln)
            if amt is None and i + 1 < len(lines):
                amt = _amount_on(lines[i + 1]) if re.fullmatch(r"\s*" + AMOUNT + r"\s*", lines[i + 1], re.I) else None
            if amt is not None:
                return amt, i
    return None, None


def find_total(lines: list[str]) -> tuple[Decimal | None, float, int | None]:
    best = (None, 0.0, None)
    for pattern, conf in TOTAL_KEYS:
        for i, ln in enumerate(lines):
            if re.search(pattern, ln, re.I) and not re.search(SUBTOTAL_KEYS, ln, re.I) and not re.search(r"total\s*(?:qty|items?|quantity)", ln, re.I):
                amt = _amount_on(ln)
                if amt is None and i + 1 < len(lines) and re.fullmatch(r"\s*" + AMOUNT + r"\s*", lines[i + 1], re.I):
                    amt = dec(AMOUNT_RE.findall(lines[i + 1])[-1])
                if amt is not None and amt > 0 and conf > best[1]:
                    best = (amt, conf, i)
                elif amt is not None and amt > 0 and conf == best[1] and best[0] is not None and amt > best[0]:
                    best = (amt, conf, i)
    if best[0] is None:
        best = _fuzzy_total(lines)
    if best[0] is None:
        # No labelled total (common when OCR splits a label from its value). A currency-marked figure such as
        # "Rs. 303" is printed on the bill, so it may be offered - with low confidence and a warning to verify.
        marked = []
        for i, ln in enumerate(lines):
            for m in re.finditer(r"(?:₹|\brs\b\.?|\binr\b)\s*(\d[\d,]*(?:\.\d{1,2})?)", ln, re.I):
                amt = dec(m.group(1))
                if amt is not None and amt > 0:
                    marked.append((amt, i))
        if len({a for a, _ in marked}) == 1:  # one unambiguous figure; several different ones -> leave empty
            best = (marked[-1][0], UNLABELLED_TOTAL_CONFIDENCE, marked[-1][1])
    return best


UNLABELLED_TOTAL_CONFIDENCE = 0.5
FUZZY_TOTAL_CONFIDENCE = 0.7

# Labels of the final amount, compacted. "payable" variants are preferred: on utility bills they are the
# rounded amount actually due.
_FUZZY_TOTAL_LABELS = {
    "payable": 1.0, "payableamount": 1.0, "payableamt": 1.0, "amountpayable": 1.0, "netpayable": 1.0, "totalpayable": 1.0,
    "grandtotal": 0.9, "billamount": 0.8, "netamount": 0.8, "totalamount": 0.8, "amountdue": 0.8, "totaldue": 0.8,
}


def _ocr_fold(s: str) -> str:
    """Folds characters OCR commonly confuses (i/l/1/|, 0/o) and drops everything but letters."""
    s = s.lower().translate(str.maketrans({"i": "l", "1": "l", "|": "l", "!": "l", "0": "o"}))
    return re.sub(r"[^a-z]", "", s)


def _fuzzy_total(lines: list[str]) -> tuple[Decimal | None, float, int | None]:
    """Total labels garbled by OCR ("Payahie(Rs)" for "Payable(Rs)", "alllAmount" for "Bill Amount")."""
    from rapidfuzz import fuzz

    folded_labels = {_ocr_fold(k): pref for k, pref in _FUZZY_TOTAL_LABELS.items()}
    best: tuple = (None, 0.0, None)
    best_rank = 0.0
    for i, ln in enumerate(lines):
        if re.search(SUBTOTAL_KEYS, ln, re.I) or re.search(TAX_KEYS, ln, re.I) or re.search(DISCOUNT_KEYS, ln, re.I):
            continue
        amt = _amount_on(ln)
        if amt is None or amt <= 0:
            continue
        head = re.split(r"\d", ln.lower(), maxsplit=1)[0]
        label = _ocr_fold(re.sub(r"\(?\b(?:rs|inr)\b\.?\)?|₹", "", head))  # "Payahie(Rs)" -> "payahle"
        if len(label) < 6:
            continue
        for target, pref in folded_labels.items():
            ratio = fuzz.ratio(label, target)
            if ratio >= 80 and pref * ratio > best_rank:
                best_rank, best = pref * ratio, (amt, FUZZY_TOTAL_CONFIDENCE, i)
    return best


def sum_labelled(lines: list[str], pattern: str, exclude: str | None = None) -> Decimal | None:
    total = None
    for ln in lines:
        if re.search(pattern, ln, re.I) and not (exclude and re.search(exclude, ln, re.I)):
            # ignore percentage-only figures like "CGST 2.5%"
            cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", "", ln)
            amt = _amount_on(cleaned)
            if amt is not None:
                total = (total or Decimal("0")) + abs(amt)
    return total


BOILERPLATE_LINE = re.compile(r"^\s*(?:customer\s*care|care|toll\s*free.*|helpline.*|thank\s*you.*)\s*$", re.I)


def guess_merchant(lines: list[str]) -> tuple[str | None, float, int | None]:
    for i, ln in enumerate(lines[:8]):
        # OCR lines join separate text boxes with wide gaps; the business name is the first segment
        # ("KERALAWATER    CUSTOMER    1916" -> "KERALAWATER").
        s = re.split(r"\s{3,}", ln.strip())[0].strip()
        if len(s) < 3 or sum(c.isalpha() for c in s) < 3 or BOILERPLATE_LINE.match(s):
            continue
        if re.search(r"tax\s*invoice|\binvoice\b|\breceipt\b|bill\s*of\s*supply|\bgstin\b|\bph(one)?\b|\bmob(ile)?\b|www\.|@|\bdate\b|cash\s*memo|\boriginal\b|\bduplicate\b|\bwelcome\b", s, re.I):
            continue
        if sum(c.isdigit() for c in s) > len(s) / 3:
            continue
        return re.sub(r"\s{2,}", " ", s)[:200], 0.65, i
    return None, 0.0, None


def parse_items(lines: list[str], start: int, end: int) -> list[dict]:
    items = []
    for ln in lines[start:end]:
        s = ln.strip()
        if len(s) < 3 or SKIP_ITEM_KEYS.search(s) or DATE_IN_LINE.search(s) or sum(c.isalpha() for c in s) < 2:
            continue
        # "Name  qty x price  total"
        m = re.match(r"^(.*?[A-Za-z].*?)\s+(\d+(?:\.\d+)?)\s*(kg|g|gm|ml|l|ltr|pcs|pc|nos)?\s*[x×@*]\s*(\d[\d,]*\.?\d*)\s+(\d[\d,]*\.\d{1,2})$", s, re.I)
        if m:
            name, qty, unit, price, total = m.group(1), dec(m.group(2)), m.group(3), dec(m.group(4)), dec(m.group(5))
        else:
            # "Name  qty  price  total"
            m = re.match(r"^(.*?[A-Za-z].*?)\s+(\d+(?:\.\d+)?)\s*(kg|g|gm|ml|l|ltr|pcs|pc|nos)?\s+(\d[\d,]*\.\d{1,2})\s+(\d[\d,]*\.\d{1,2})$", s, re.I)
            if m:
                name, qty, unit, price, total = m.group(1), dec(m.group(2)), m.group(3), dec(m.group(4)), dec(m.group(5))
            else:
                # "Name  total"
                m = re.match(r"^(.*?[A-Za-z].*?)\s{2,}(\d[\d,]*\.\d{1,2})$", s) or re.match(r"^(.*?[A-Za-z][^\d]*?)\s+(\d[\d,]*\.\d{2})$", s)
                if not m:
                    continue
                name, qty, unit, price, total = m.group(1), None, None, None, dec(m.group(2))
        name = re.sub(r"\s{2,}", " ", name).strip(" -:.")
        if not name or total is None:
            continue
        # Package size in the name ("Rice 5kg") with a count -> total quantity in that unit.
        size = SIZE_RE.search(name)
        if unit is None and size:
            pkg_qty, pkg_unit = dec(size.group(1)), size.group(2).lower()
            count = qty if qty is not None else Decimal("1")
            if pkg_unit not in ("pcs", "pc"):
                qty, unit = count * pkg_qty, pkg_unit
                if price is not None and count:
                    price = None  # the printed price is per pack, not per unit of measure
        elif unit is None and qty is not None:
            unit = "pcs"
        conf = 0.8 if qty is not None else 0.6
        items.append(
            {
                "name": name[:300],
                "quantity": format(qty, "f") if qty is not None else None,
                "unit": unit.lower() if unit else None,
                "unit_price": format(price, "f") if price is not None else None,
                "line_total": format(total, "f"),
                "confidence": conf,
            }
        )
    return items


def detect_kind(text: str) -> str:
    t = text.lower()
    if re.search(r"paid\s+to|payment\s+successful|money\s+sent|sent\s+to|transfer\s+successful|upi\s+transaction\s+id", t) and not re.search(r"tax\s*invoice|qty|sub\s*total", t):
        return "upi_screenshot"
    if re.search(r"tax\s*invoice|invoice\s*(no|number|date)", t):
        return "invoice"
    return "receipt"


def parse_upi_screenshot(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    payee = None
    for i, ln in enumerate(lines):
        m = re.match(r"(?:paid\s+to|sent\s+to|to)\s*[:\-]?\s*(.+)$", ln, re.I)
        if m and m.group(1).strip():
            payee = m.group(1).strip()
            break
        if re.fullmatch(r"(?:paid\s+to|sent\s+to|to)", ln, re.I) and i + 1 < len(lines):
            payee = lines[i + 1]
            break
    amt = None
    # OCR often reads the rupee sign as "Rs"; the amount is the first currency-marked figure.
    m = re.search(r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
    if m:
        amt = dec(m.group(1))
    d, dconf = parse_date(text)
    t, tconf = parse_time(text)
    ref, rconf = find_reference(text)
    vpa = re.search(r"\b[a-z0-9.\-_]{2,}@[a-z]{2,}\b", text, re.I)
    status_failed = re.search(r"failed|declined|reversed|pending", text, re.I)
    return {
        "merchant_name": F(payee, 0.8),
        "merchant_address": F(None, 0),
        "invoice_number": F(None, 0),
        "date": F(d.isoformat() if d else None, dconf),
        "time": F(t.isoformat() if t else None, tconf),
        "currency": F("INR" if amt is not None else None, 0.9),
        "subtotal": F(None, 0),
        "discount": F(None, 0),
        "tax": F(None, 0),
        "charges": F(None, 0),
        "total": F(format(amt, "f") if amt is not None else None, 0.9),
        "payment_method": F("upi", 0.95),
        "payment_reference": F(ref, rconf),
        "order_id": F(None, 0),
        "payee_vpa": F(vpa.group(0).lower() if vpa else None, 0.9),
        "gstin": F(None, 0),
        "payment_status": F("not_completed" if status_failed else "completed", 0.7),
    }


def validate(fields: dict, items: list[dict]) -> list[dict]:
    issues = []
    v = lambda k: fields.get(k, {}).get("value")  # noqa: E731
    total = dec(v("total"))
    if total is None:
        issues.append({"level": "error", "code": "total_missing", "message": "Total amount was not found. Enter it before confirming."})
    elif (fields.get("total") or {}).get("confidence") == FUZZY_TOTAL_CONFIDENCE and not (fields.get("total") or {}).get("edited"):
        issues.append({"level": "info", "code": "total_fuzzy_label", "message": f"The total ({total}) is next to a label that looks like 'Payable' or 'Bill Amount' but was misread. Check it against the bill."})
    elif (fields.get("total") or {}).get("confidence", 1) <= UNLABELLED_TOTAL_CONFIDENCE and not (fields.get("total") or {}).get("edited"):
        issues.append({"level": "warning", "code": "total_unlabelled", "message": f"The total ({total}) was taken from an amount marked with a currency sign, not from a 'Total' line. Check it against the bill."})
    if not v("date"):
        issues.append({"level": "error", "code": "date_missing", "message": "Date was not found. Enter it before confirming."})
    elif v("date") > date.today().isoformat():
        issues.append({"level": "warning", "code": "date_future", "message": "The date is in the future - check it."})
    if not v("merchant_name"):
        issues.append({"level": "warning", "code": "merchant_missing", "message": "Merchant name was not found."})
    if not v("currency"):
        issues.append({"level": "info", "code": "currency_missing", "message": "No currency symbol found; the workspace currency will be used unless you change it."})
    if fields.get("payment_status", {}).get("value") == "not_completed":
        issues.append({"level": "error", "code": "payment_not_completed", "message": "The screenshot indicates a failed, pending or reversed payment - it should not be recorded as a completed expense."})
    for i, it in enumerate(items):
        q, p, lt = dec(it.get("quantity")), dec(it.get("unit_price")), dec(it.get("line_total"))
        if q is not None and p is not None and lt is not None and abs(q * p - lt) > Decimal("1.00"):
            issues.append({"level": "warning", "code": "line_mismatch", "message": f"Line {i + 1} ({it['name']}): {q} × {p} ≠ {lt}", "line": i})
    items_sum = sum((dec(it.get("line_total")) or Decimal("0") for it in items), Decimal("0")) if items else None
    subtotal = dec(v("subtotal"))
    base = subtotal if subtotal is not None else None
    if items_sum is not None and subtotal is not None and abs(items_sum - subtotal) > Decimal("1.00"):
        issues.append({"level": "warning", "code": "items_vs_subtotal", "message": f"Line items add up to {items_sum}, but the subtotal is {subtotal}. Some items may be missing or misread."})
    if base is None and items_sum is not None:
        base = items_sum
    if total is not None and base is not None:
        expected = base - (dec(v("discount")) or 0) + (dec(v("tax")) or 0) + (dec(v("charges")) or 0) + (dec(v("rounding")) or 0)
        # Tax-inclusive receipts list GST as information only: accept either reading.
        expected_inclusive = base - (dec(v("discount")) or 0) + (dec(v("charges")) or 0) + (dec(v("rounding")) or 0)
        if abs(expected - total) > Decimal("1.00") and abs(expected_inclusive - total) > Decimal("1.00"):
            issues.append(
                {"level": "warning", "code": "total_mismatch", "message": f"Subtotal/items ({base}) adjusted for discount, tax and charges give {expected}, but the total is {total}."}
            )
    if total is not None and total <= 0:
        issues.append({"level": "error", "code": "total_invalid", "message": "Total must be greater than zero."})
    return issues


def parse_document(text: str) -> dict:
    """Returns {"kind", "fields", "line_items", "validation", "overall_confidence"}."""
    kind = detect_kind(text)
    if kind == "upi_screenshot":
        fields = parse_upi_screenshot(text)
        items: list[dict] = []
    else:
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        merchant, mconf, midx = guess_merchant(lines)
        address = None
        if midx is not None:
            addr_lines = []
            for ln in lines[midx + 1 : midx + 4]:
                if re.search(r"\bgstin\b|\bph(one)?\b|\bmob(ile)?\b|\binvoice\b|\bbill\b|\bdate\b|\btel\b", ln, re.I):
                    break
                if re.search(r"[,\-]|\d{6}|road|street|nagar|st\.|rd\.", ln, re.I):
                    addr_lines.append(ln.strip())
            address = ", ".join(addr_lines) or None
        d, dconf = parse_date(text)
        t, tconf = parse_time(text)
        total, tconf_total, tidx = find_total(lines)
        subtotal, sidx = _labelled_amount(lines, SUBTOTAL_KEYS)
        tax = sum_labelled(lines, TAX_KEYS, exclude=r"gstin|incl|inclusive|taxable")
        discount = sum_labelled(lines, DISCOUNT_KEYS)
        charges = sum_labelled(lines, CHARGE_KEYS)
        rounding = None
        for ln in lines:
            if re.search(ROUND_KEYS, ln, re.I):
                rounding = _amount_on(ln)
        currency, cconf = detect_currency(text)
        method, pconf = detect_payment_method(text)
        ref, rconf = find_reference(text)
        inv, iconf = find_invoice_number(text)
        order, oconf = find_order_id(text)
        gstin = re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b", text)
        # Items live between the header and the first subtotal/total line.
        start = (midx + 1) if midx is not None else 0
        end_candidates = [i for i in (sidx, tidx) if i is not None]
        end = min(end_candidates) if end_candidates else len(lines)
        items = parse_items(lines, start, end)
        fields = {
            "merchant_name": F(merchant, mconf),
            "merchant_address": F(address, 0.4),
            "invoice_number": F(inv, iconf),
            "date": F(d.isoformat() if d else None, dconf),
            "time": F(t.isoformat() if t else None, tconf),
            "currency": F(currency, cconf),
            "subtotal": F(format(subtotal, "f") if subtotal is not None else None, 0.8),
            "discount": F(format(discount, "f") if discount is not None else None, 0.75),
            "tax": F(format(tax, "f") if tax is not None else None, 0.75),
            "charges": F(format(charges, "f") if charges is not None else None, 0.7),
            "rounding": F(format(rounding, "f") if rounding is not None else None, 0.7),
            "total": F(format(total, "f") if total is not None else None, tconf_total),
            "payment_method": F(method, pconf),
            "payment_reference": F(ref, rconf),
            "order_id": F(order, oconf),
            "gstin": F(gstin.group(0) if gstin else None, 0.95),
        }
    issues = validate(fields, items)
    key = [fields["total"]["confidence"], fields["date"]["confidence"], fields["merchant_name"]["confidence"]]
    overall = sum(key) / len(key)
    overall -= 0.15 * sum(1 for i in issues if i["level"] == "error") + 0.05 * sum(1 for i in issues if i["level"] == "warning")
    return {"kind": kind, "fields": fields, "line_items": items, "validation": issues, "overall_confidence": max(0.0, round(overall, 3))}


def combine_datetime(d: str | None, t: str | None) -> datetime | None:
    if not d or not t:
        return None
    try:
        return datetime.fromisoformat(f"{d}T{t}")
    except ValueError:
        return None

"""Deterministic merchant-name normalisation and payee extraction from bank/UPI narrations."""
import re

from rapidfuzz import fuzz

LEGAL_SUFFIXES = {"pvt", "private", "ltd", "limited", "llp", "inc", "co", "corp", "company", "and", "the", "&"}
GENERIC_WORDS = {
    "supermarket", "super", "market", "hypermarket", "store", "stores", "shop", "restaurant", "restaurants", "hotel",
    "cafe", "bakery", "pharmacy", "medicals", "medical", "enterprises", "enterprise", "traders", "trading", "services",
    "service", "agencies", "foods", "food", "retail", "outlet", "branch", "india", "online", "payments", "payment",
}
CITIES = {
    "trivandrum", "thiruvananthapuram", "kochi", "cochin", "ernakulam", "kozhikode", "calicut", "thrissur", "kollam",
    "bangalore", "bengaluru", "chennai", "mumbai", "delhi", "newdelhi", "hyderabad", "pune", "kolkata", "ahmedabad",
    "noida", "gurgaon", "gurugram", "jaipur", "lucknow", "mysore", "mangalore", "coimbatore", "madurai", "kerala",
}


def _tokens(name: str) -> list[str]:
    s = (name or "").lower()
    s = re.sub(r"[@].*$", "", s) if "@" in s and " " not in s.strip() else s  # bare UPI VPA -> handle part
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return [t for t in s.split() if t]


def normalize_merchant(name: str) -> str:
    """'Fresh Mart Supermarket' -> 'freshmart'; 'FRESHMART TRIVANDRUM' -> 'freshmart'; 'ABC Restaurant' -> 'abc'."""
    toks = [t for t in _tokens(name) if t not in LEGAL_SUFFIXES and t not in CITIES and not t.isdigit()]
    core = [t for t in toks if t not in GENERIC_WORDS]
    if not core:  # never normalise a name down to nothing
        core = toks
    return "".join(core)[:200]


def display_tokens(name: str) -> str:
    toks = [t for t in _tokens(name) if t not in LEGAL_SUFFIXES and t not in CITIES]
    return " ".join(toks)


def merchant_similarity(a: str, b: str) -> float:
    """0..1 similarity on normalised forms; combines compact and token-set comparisons."""
    na, nb = normalize_merchant(a), normalize_merchant(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    compact = fuzz.ratio(na, nb) / 100
    token = fuzz.token_set_ratio(display_tokens(a), display_tokens(b)) / 100
    # A prefix match on compact names ("freshmart" vs "freshmarttvm") is strong evidence.
    prefix = 0.92 if (len(na) >= 5 and len(nb) >= 5 and (na.startswith(nb) or nb.startswith(na))) else 0.0
    return round(max(compact, token * 0.95, prefix), 3)


UPI_ID_RE = re.compile(r"\b([a-z0-9.\-_]{2,})@([a-z]{2,})\b", re.I)
REF_12_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")


def parse_narration(text: str) -> dict:
    """Extract payee, UPI VPA and reference from common Indian bank statement narrations.

    Handles e.g. 'UPI/DR/429112345678/FRESHMART TRIVA/SBIN/freshmart@okaxis/Payment',
    'UPI-ABC RESTAURANT-abcrest@ybl-HDFC0001234-429112345678-dinner', 'POS 4XXX1234 DMART AVENUE'.
    Values that are not present are returned as None.
    """
    t = (text or "").strip()
    out = {"payee": None, "vpa": None, "reference": None, "channel": None}
    vpa = UPI_ID_RE.search(t)
    if vpa:
        out["vpa"] = vpa.group(0).lower()
    ref = REF_12_RE.search(t)
    if ref:
        out["reference"] = ref.group(1)
    up = t.upper()
    if up.startswith("UPI"):
        out["channel"] = "upi"
        parts = [p.strip() for p in re.split(r"[/\-]", t) if p.strip()]
        for p in parts[1:]:
            pu = p.upper()
            if pu in {"DR", "CR", "UPI", "P2M", "P2A", "PAY", "COLLECT"} or p.isdigit() or "@" in p or re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", pu) or re.fullmatch(r"[A-Z]{4}", pu):
                continue
            if len(p) >= 3:
                out["payee"] = p.strip()
                break
    elif up.startswith(("POS", "ECOM", "PCD", "VPS")):
        out["channel"] = "card"
        m = re.sub(r"^(POS|ECOM|PCD|VPS)\s*(PURCHASE)?\s*[\dX*]*\s*", "", t, flags=re.I)
        out["payee"] = m.strip() or None
    elif up.startswith(("NEFT", "IMPS", "RTGS")):
        out["channel"] = "bank_transfer"
        parts = [p.strip() for p in re.split(r"[/\-]", t) if p.strip()]
        names = [p for p in parts[1:] if not any(ch.isdigit() for ch in p) and len(p) > 2 and not re.fullmatch(r"[A-Z]{4}", p.upper())]
        out["payee"] = names[0] if names else None
    if out["payee"] is None and out["vpa"]:
        out["payee"] = out["vpa"].split("@")[0]
    return out

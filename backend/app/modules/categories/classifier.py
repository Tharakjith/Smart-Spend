"""Evidence-scoring expense classifier.

Every signal that a bill or transaction carries is weighed: the merchant name, the description / bank narration,
line items, and the full text of an uploaded bill (utility bills describe themselves in the body - "Water Charge",
"kWh", "Sewerage" - not in the header). Terms are matched as whole words and, for distinctive terms, inside
run-together OCR text ("KERALAWATER"). The winning category must clear a minimum score and beat the runner-up by a
margin; otherwise nothing is guessed. Every decision carries the matched evidence so the UI can explain it.
"""
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

# Weight of a match by where it was found.
FIELD_WEIGHTS = {"merchant": 3.0, "description": 2.0, "item": 1.0, "document": 1.0}
MIN_SCORE = 3.0  # e.g. one medium term in the merchant name, or two in the bill text
MARGIN = 1.3  # the winner must beat the runner-up (another main category) by 30%
CHILD_MIN = 1.5  # a subcategory is chosen only when it has its own evidence
DIMINISHING = (1.0, 0.5, 0.25)  # weight of the 1st, 2nd and 3rd distinct term found in one field

STRONG, MEDIUM, WEAK = 3.0, 2.0, 1.0

# Category path -> {term: weight}. Paths are "Main" or "Main/Sub" and resolve against the household's categories.
TERMS: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------ utilities
    "Electricity and Utilities": {"consumer no": WEAK, "consumer number": WEAK, "consumer id": WEAK, "meter no": WEAK, "meter reading": WEAK, "meterrent": WEAK, "connection id": WEAK, "conn id": WEAK, "disconnection": WEAK, "fixed charge": WEAK, "utility": MEDIUM, "utilities": MEDIUM},
    "Electricity and Utilities/Electricity": {
        "electricity": STRONG, "electrical energy": STRONG, "kwh": STRONG, "kseb": STRONG, "ksebl": STRONG, "bescom": STRONG, "tangedco": STRONG, "tneb": STRONG,
        "msedcl": STRONG, "mahadiscom": STRONG, "cesc": STRONG, "bses": STRONG, "tata power": STRONG, "adani electricity": STRONG, "torrent power": STRONG,
        "apspdcl": STRONG, "tsspdcl": STRONG, "uppcl": STRONG, "pspcl": STRONG, "wbsedcl": STRONG, "dhbvn": STRONG, "uhbvn": STRONG, "jvvnl": STRONG, "avvnl": STRONG,
        "hescom": STRONG, "mescom": STRONG, "electricity board": STRONG, "power supply": MEDIUM, "fuelsurcharge": MEDIUM, "fueladjustment": MEDIUM, "energy charge": STRONG,
        "units consumed": MEDIUM, "supply code": MEDIUM, "tariff": WEAK, "power": WEAK,
    },
    "Electricity and Utilities/Water": {
        "water": MEDIUM, "water charge": STRONG, "water charges": STRONG, "water bill": STRONG, "water authority": STRONG, "water supply": STRONG, "water tax": STRONG,
        "sewerage": STRONG, "sewage": STRONG, "jal board": STRONG, "jal nigam": STRONG, "kwa": STRONG, "bwssb": STRONG, "hmwssb": STRONG, "cmwssb": STRONG,
        "metrowater": STRONG, "kilolitre": STRONG, "kilo litre": STRONG, "conskl": STRONG, "drinking water": WEAK,
    },
    "Electricity and Utilities/Gas": {
        "lpg": STRONG, "cylinder": MEDIUM, "indane": STRONG, "hp gas": STRONG, "hpgas": STRONG, "bharat gas": STRONG, "bharatgas": STRONG, "piped gas": STRONG,
        "png": MEDIUM, "igl": STRONG, "mgl": STRONG, "gail gas": STRONG, "gujarat gas": STRONG, "adani gas": STRONG, "gas booking": STRONG, "scm": WEAK,
    },
    "Electricity and Utilities/Broadband": {
        "broadband": STRONG, "fiber": MEDIUM, "fibre": MEDIUM, "fibernet": STRONG, "ftth": STRONG, "act fibernet": STRONG, "jiofiber": STRONG, "airtel xstream": STRONG,
        "asianet": STRONG, "hathway": STRONG, "excitel": STRONG, "you broadband": STRONG, "internet": MEDIUM, "wifi": MEDIUM, "landline": MEDIUM, "dth": MEDIUM,
        "tata play": STRONG, "tatasky": STRONG, "tata sky": STRONG, "dish tv": STRONG, "sun direct": STRONG, "d2h": STRONG,
    },
    "Electricity and Utilities/Mobile": {
        "recharge": MEDIUM, "prepaid": MEDIUM, "postpaid": STRONG, "mobile bill": STRONG, "airtel": MEDIUM, "jio": MEDIUM, "vodafone": MEDIUM, "vi prepaid": STRONG,
        "bsnl": MEDIUM, "talktime": STRONG, "data pack": STRONG, "sim": WEAK,
    },
    # ------------------------------------------------------------------ food
    "Food and Dining": {"food": WEAK, "meal": MEDIUM, "meals": MEDIUM, "dine": MEDIUM, "dining": MEDIUM, "kot": MEDIUM, "table no": MEDIUM, "covers": WEAK, "pax": WEAK},
    "Food and Dining/Restaurants": {
        "restaurant": STRONG, "restaurants": STRONG, "hotel": MEDIUM, "dhaba": STRONG, "biryani": STRONG, "mess": MEDIUM, "kitchen": WEAK, "grill": MEDIUM, "bbq": MEDIUM,
        "mandi": MEDIUM, "paradise": WEAK, "dominos": STRONG, "domino s": STRONG, "pizza": STRONG, "mcdonald": STRONG, "kfc": STRONG, "burger": STRONG, "subway": MEDIUM,
        "naan": MEDIUM, "paneer": WEAK, "thali": STRONG, "dosa": MEDIUM, "porotta": MEDIUM, "shawarma": STRONG, "service charge": WEAK, "dine in": STRONG,
    },
    "Food and Dining/Cafes & Snacks": {
        "cafe": STRONG, "coffee": MEDIUM, "tea": MEDIUM, "chai": MEDIUM, "bakery": STRONG, "bakes": MEDIUM, "juice": MEDIUM, "snacks": MEDIUM, "starbucks": STRONG,
        "ccd": STRONG, "cafe coffee day": STRONG, "chaayos": STRONG, "ice cream": STRONG, "baskin": STRONG, "sweets": MEDIUM, "chaat": MEDIUM, "tea stall": STRONG,
    },
    "Food and Dining/Food Delivery": {"swiggy": STRONG, "zomato": STRONG, "eatsure": STRONG, "magicpin": MEDIUM, "food delivery": STRONG, "ubereats": STRONG},
    # ------------------------------------------------------------------ groceries
    "Groceries": {
        "grocery": STRONG, "groceries": STRONG, "supermarket": STRONG, "hypermarket": STRONG, "provision": STRONG, "provisions": STRONG, "kirana": STRONG, "mart": MEDIUM,
        "dmart": STRONG, "d mart": STRONG, "avenue supermarts": STRONG, "bigbasket": STRONG, "big basket": STRONG, "blinkit": STRONG, "zepto": STRONG, "jiomart": STRONG,
        "instamart": STRONG, "reliance fresh": STRONG, "reliance smart": STRONG, "more retail": STRONG, "more supermarket": STRONG, "spencers": STRONG, "nilgiris": STRONG,
        "ratnadeep": STRONG, "lulu hypermarket": STRONG, "star bazaar": STRONG, "vegetables": MEDIUM, "fruits": MEDIUM, "milk": WEAK, "rice": WEAK, "atta": WEAK, "dal": WEAK,
        "supplyco": STRONG, "maveli": STRONG, "ration": MEDIUM,
    },
    # ------------------------------------------------------------------ housing
    "Housing and Rent/Rent": {"rent": STRONG, "house rent": STRONG, "rental": MEDIUM, "lease": MEDIUM, "pg rent": STRONG, "hostel fee": MEDIUM, "landlord": STRONG},
    "Housing and Rent/Maintenance & Repairs": {
        "maintenance": MEDIUM, "society maintenance": STRONG, "repair": MEDIUM, "repairs": MEDIUM, "plumber": STRONG, "plumbing": STRONG, "electrician": STRONG,
        "carpenter": STRONG, "painting": MEDIUM, "pest control": STRONG, "urban company": STRONG, "ac service": STRONG, "ro service": STRONG, "hardware": MEDIUM,
    },
    "Housing and Rent/Furnishing": {"furniture": STRONG, "ikea": STRONG, "pepperfry": STRONG, "urban ladder": STRONG, "mattress": STRONG, "curtains": STRONG, "sofa": STRONG},
    # ------------------------------------------------------------------ transport
    "Transportation and Fuel/Fuel": {
        "petrol": STRONG, "diesel": STRONG, "fuel": STRONG, "filling station": STRONG, "fuel station": STRONG, "petroleum": STRONG, "indian oil": STRONG, "iocl": STRONG,
        "bpcl": STRONG, "bharat petroleum": STRONG, "hpcl": STRONG, "hindustan petroleum": STRONG, "nayara": STRONG, "shell": MEDIUM, "jio bp": STRONG, "cng": STRONG,
        "litres": WEAK, "ltrs": WEAK, "pump": WEAK,
    },
    "Transportation and Fuel/Cab & Auto": {"uber": STRONG, "ola": STRONG, "ola cabs": STRONG, "rapido": STRONG, "taxi": STRONG, "cab": MEDIUM, "auto rickshaw": STRONG, "blusmart": STRONG, "namma yatri": STRONG},
    "Transportation and Fuel/Public Transport": {"metro": MEDIUM, "ksrtc": STRONG, "bmtc": STRONG, "best bus": STRONG, "bus ticket": STRONG, "bus": WEAK, "redbus": STRONG, "local train": STRONG, "suburban": MEDIUM},
    "Transportation and Fuel/Vehicle Service": {"service centre": MEDIUM, "service center": MEDIUM, "car service": STRONG, "bike service": STRONG, "tyre": STRONG, "tyres": STRONG, "puncture": STRONG, "engine oil": STRONG, "car wash": STRONG, "spare parts": STRONG, "motors": WEAK},
    "Transportation and Fuel/Parking & Tolls": {"toll": STRONG, "fastag": STRONG, "parking": STRONG, "toll plaza": STRONG, "nhai": STRONG},
    # ------------------------------------------------------------------ shopping
    "Shopping/Online Shopping": {"amazon": STRONG, "flipkart": STRONG, "meesho": STRONG, "snapdeal": STRONG, "tatacliq": STRONG, "tata cliq": STRONG, "nykaa": MEDIUM, "online order": MEDIUM},
    "Shopping/Clothing": {"myntra": STRONG, "ajio": STRONG, "trends": MEDIUM, "pantaloons": STRONG, "westside": STRONG, "max fashion": STRONG, "zudio": STRONG, "lifestyle": MEDIUM, "textiles": STRONG, "garments": STRONG, "apparel": STRONG, "fashion": MEDIUM, "silks": STRONG, "footwear": STRONG, "bata": STRONG, "shirt": MEDIUM, "saree": STRONG, "jeans": STRONG},
    "Shopping/Electronics": {"croma": STRONG, "reliance digital": STRONG, "vijay sales": STRONG, "electronics": STRONG, "mobile phone": MEDIUM, "laptop": STRONG, "headphones": STRONG, "television": STRONG, "samsung": MEDIUM, "apple store": STRONG, "oppo": MEDIUM, "vivo": MEDIUM},
    "Shopping/Home & Kitchen": {"home centre": STRONG, "kitchen appliances": STRONG, "utensils": STRONG, "cookware": STRONG, "decathlon": MEDIUM, "home needs": MEDIUM},
    "Shopping": {"shopping": MEDIUM, "store": WEAK, "stores": WEAK, "mall": MEDIUM, "retail": WEAK},
    # ------------------------------------------------------------------ health
    "Healthcare and Medicines/Medicines": {
        "pharmacy": STRONG, "pharma": MEDIUM, "medical store": STRONG, "medicals": STRONG, "chemist": STRONG, "druggist": STRONG, "medicine": STRONG, "medicines": STRONG,
        "apollo pharmacy": STRONG, "medplus": STRONG, "netmeds": STRONG, "1mg": STRONG, "pharmeasy": STRONG, "tablet": MEDIUM, "tablets": MEDIUM, "tab": WEAK, "syrup": MEDIUM, "capsule": MEDIUM, "batch no": WEAK, "exp date": WEAK,
    },
    "Healthcare and Medicines/Doctor & Hospital": {"hospital": STRONG, "clinic": STRONG, "doctor": STRONG, "dr": WEAK, "consultation": STRONG, "opd": STRONG, "ipd": STRONG, "dental": STRONG, "dentist": STRONG, "nursing home": STRONG, "medical college": STRONG, "health centre": STRONG, "physiotherapy": STRONG},
    "Healthcare and Medicines/Diagnostics": {"diagnostic": STRONG, "diagnostics": STRONG, "laboratory": STRONG, "lab": MEDIUM, "pathology": STRONG, "scan": MEDIUM, "x ray": STRONG, "mri": STRONG, "blood test": STRONG, "thyrocare": STRONG, "dr lal": STRONG, "metropolis": STRONG},
    # ------------------------------------------------------------------ others
    "Education/Tuition & Fees": {"school": STRONG, "college": STRONG, "university": STRONG, "tuition": STRONG, "tuition fee": STRONG, "admission": MEDIUM, "exam fee": STRONG, "coaching": STRONG, "academy": MEDIUM, "fees": WEAK},
    "Education/Books & Courses": {"book": MEDIUM, "books": MEDIUM, "bookstore": STRONG, "stationery": MEDIUM, "course": MEDIUM, "udemy": STRONG, "coursera": STRONG, "byjus": STRONG, "unacademy": STRONG},
    "Travel and Accommodation/Flights & Trains": {"irctc": STRONG, "railway": STRONG, "train": STRONG, "flight": STRONG, "airline": STRONG, "airlines": STRONG, "indigo": STRONG, "air india": STRONG, "vistara": STRONG, "spicejet": STRONG, "akasa": STRONG, "pnr": STRONG, "boarding": MEDIUM},
    "Travel and Accommodation/Hotels": {"oyo": STRONG, "resort": STRONG, "lodge": STRONG, "homestay": STRONG, "room tariff": STRONG, "check in": MEDIUM, "booking com": STRONG, "airbnb": STRONG, "treebo": STRONG, "fabhotels": STRONG},
    "Travel and Accommodation": {"makemytrip": STRONG, "goibibo": STRONG, "cleartrip": STRONG, "yatra": STRONG, "easemytrip": STRONG, "travels": MEDIUM, "tour": MEDIUM, "holiday": MEDIUM},
    "Entertainment and Gaming/Movies & Events": {"bookmyshow": STRONG, "pvr": STRONG, "inox": STRONG, "cinepolis": STRONG, "cinema": STRONG, "movie": STRONG, "theatre": MEDIUM, "concert": STRONG, "tickets": WEAK},
    "Entertainment and Gaming/Gaming": {"steam": STRONG, "playstation": STRONG, "xbox": STRONG, "google play": MEDIUM, "dream11": STRONG, "gaming": STRONG},
    "Entertainment and Gaming/Streaming": {"netflix": STRONG, "hotstar": STRONG, "disney": STRONG, "prime video": STRONG, "sonyliv": STRONG, "zee5": STRONG, "spotify": STRONG, "jiocinema": STRONG, "youtube premium": STRONG, "gaana": STRONG},
    "Subscriptions/Software & Apps": {"subscription": MEDIUM, "google one": STRONG, "icloud": STRONG, "microsoft 365": STRONG, "office 365": STRONG, "adobe": STRONG, "chatgpt": STRONG, "openai": STRONG, "anthropic": STRONG, "claude ai": STRONG, "app store": MEDIUM},
    "Subscriptions/Memberships": {"membership": STRONG, "club": MEDIUM, "amazon prime": STRONG},
    "Personal Care/Salon & Grooming": {"salon": STRONG, "saloon": STRONG, "barber": STRONG, "spa": STRONG, "parlour": STRONG, "parlor": STRONG, "haircut": STRONG, "beauty": MEDIUM, "naturals": MEDIUM},
    "Personal Care/Cosmetics": {"cosmetics": STRONG, "nykaa": STRONG, "shampoo": MEDIUM, "lotion": MEDIUM, "perfume": STRONG, "makeup": STRONG},
    "Personal Care/Fitness": {"gym": STRONG, "fitness": STRONG, "cult fit": STRONG, "cultfit": STRONG, "yoga": STRONG, "protein": MEDIUM},
    "Insurance/Health Insurance": {"health insurance": STRONG, "mediclaim": STRONG, "star health": STRONG, "niva bupa": STRONG, "care health": STRONG},
    "Insurance/Vehicle Insurance": {"motor insurance": STRONG, "car insurance": STRONG, "bike insurance": STRONG, "two wheeler insurance": STRONG},
    "Insurance/Life Insurance": {"lic": STRONG, "life insurance": STRONG, "term plan": STRONG, "lic of india": STRONG},
    "Insurance": {"insurance": STRONG, "premium": MEDIUM, "policy": MEDIUM, "policy no": STRONG, "hdfc ergo": STRONG, "icici lombard": STRONG, "bajaj allianz": STRONG, "tata aig": STRONG},
    "Loan Interest and Financial Charges/Loan Interest": {"interest": MEDIUM, "loan interest": STRONG, "emi interest": STRONG},
    "Loan Interest and Financial Charges/Bank Charges": {"bank charges": STRONG, "sms charges": STRONG, "annual fee": STRONG, "processing fee": STRONG, "min bal": STRONG, "minimum balance": STRONG, "atm fee": STRONG, "convenience fee": WEAK},
    "Loan Interest and Financial Charges/Late Fees": {"late fee": STRONG, "late payment": STRONG, "penalty": STRONG, "overdue charges": STRONG},
    "Gifts and Donations/Donations & Charity": {"donation": STRONG, "charity": STRONG, "temple": STRONG, "church": STRONG, "mosque": STRONG, "masjid": STRONG, "devaswom": STRONG, "trust": WEAK, "foundation": WEAK, "offering": MEDIUM},
    "Gifts and Donations/Gifts": {"gift": STRONG, "gifts": STRONG, "florist": STRONG, "flowers": MEDIUM, "ferns n petals": STRONG, "archies": STRONG},
    "Taxes/Income Tax": {"income tax": STRONG, "tds": MEDIUM, "advance tax": STRONG, "self assessment tax": STRONG},
    "Taxes/Property Tax": {"property tax": STRONG, "building tax": STRONG, "municipal tax": STRONG, "panchayat": MEDIUM, "corporation tax": MEDIUM},
    "Work and Business Expenses/Office Supplies": {"office supplies": STRONG, "printer": MEDIUM, "toner": STRONG, "xerox": STRONG, "photocopy": STRONG, "courier": MEDIUM},
    # ------------------------------------------------------------------ income
    "Salary": {"salary": STRONG, "sal": MEDIUM, "payroll": STRONG, "wages": STRONG},
    "Interest and Dividends": {"interest": MEDIUM, "int pd": STRONG, "int credit": STRONG, "dividend": STRONG, "fd interest": STRONG, "sb interest": STRONG},
    "Business Income": {"invoice payment": MEDIUM, "consulting": MEDIUM, "client": WEAK},
}

# Distinctive terms that may be matched inside run-together OCR text ("KERALAWATER", "PETROLPUMP").
# Short or generic terms are excluded because they occur inside unrelated words ("tab" in "table").
_SUBSTRING_MIN_LEN = 5
_NO_SUBSTRING = {"power", "store", "stores", "trust", "travels", "fiber", "fibre", "cylinder", "trends", "lifestyle", "beauty", "client", "premium", "policy", "interest", "fashion", "kitchen", "boarding", "theatre", "tickets", "flowers", "course", "books"}


@dataclass
class Decision:
    path: str | None
    score: float
    confidence: float
    reasons: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)


# Phrases whose words would mislead word matching ("Meter Rent" is not house rent, "Fuel Surcharge" on an
# electricity bill is not petrol, a "water bottle" in a restaurant is not a water bill). They are joined into
# single tokens before scoring; terms that need them refer to the joined form.
CONFUSABLE_PHRASES = {
    "meter rent": "meterrent",
    "fuel surcharge": "fuelsurcharge",
    "fuel adjustment": "fueladjustment",
    "water bottle": "waterbottle",
    "mineral water": "mineralwater",
    "packaged drinking water": "packageddrinkingwater",
    "rent a car": "rentacar",
    "service tax": "servicetax",
}


_READABLE = {joined: phrase for phrase, joined in CONFUSABLE_PHRASES.items()}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = f" {re.sub(r' +', ' ', t).strip()} "
    for phrase, joined in CONFUSABLE_PHRASES.items():
        t = t.replace(f" {phrase} ", f" {joined} ")
    return t


def _compact(text: str) -> str:
    # Joined confusable phrases are dropped here, or "mineralwater" would still contain "water".
    t = normalize(text)
    for joined in CONFUSABLE_PHRASES.values():
        t = t.replace(f" {joined} ", " ")
    return t.replace(" ", "")


def _matches(term: str, norm: str, compact: str) -> bool:
    if f" {term} " in norm:
        return True
    if len(term.replace(" ", "")) >= _SUBSTRING_MIN_LEN and term not in _NO_SUBSTRING:
        return term.replace(" ", "") in compact
    return False


def classify(
    *,
    merchant: str = "",
    description: str = "",
    items: list[str] | None = None,
    document_text: str = "",
    allowed_paths: set[str] | None = None,
    extra_terms: dict[str, dict[str, float]] | None = None,
    item_terms: dict[str, dict[str, float]] | None = None,
) -> Decision:
    """Scores every category path and returns the best one, or path=None when the evidence is too weak."""
    def merged(*sources: dict[str, dict[str, float]] | None) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for src in sources:
            for path, t in (src or {}).items():
                out[path] = {**out.get(path, {}), **t}
        if allowed_paths is not None:
            out = {p: t for p, t in out.items() if p.split("/")[0] in allowed_paths}
        return out

    terms = merged(TERMS, extra_terms)
    terms_for_items = merged(TERMS, extra_terms, item_terms)  # item keywords only apply to line items
    fields = [("merchant", merchant), ("description", description), ("document", document_text)] + [("item", i) for i in (items or [])]
    own: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)
    for fname, raw in fields:
        if not raw:
            continue
        norm, compact = normalize(raw), _compact(raw)
        weight = FIELD_WEIGHTS[fname]
        label = {"merchant": "merchant", "description": "description", "document": "bill text", "item": "item"}[fname]
        for path, tmap in (terms_for_items if fname == "item" else terms).items():
            hits = sorted(((w, term) for term, w in tmap.items() if _matches(term, norm, compact)), reverse=True)
            if not hits:
                continue
            # Several distinct terms in one field are stronger evidence than one ("Hospital" + "OPD" +
            # "Consultation" beats a lone "Medicine"), with diminishing returns so long bills don't run away.
            own[path] += sum(w * f for (w, _), f in zip(hits, DIMINISHING)) * weight
            evidence[path].extend(f"{label}: '{_READABLE.get(term, term)}'" for _, term in hits[:2])
    tops: dict[str, float] = defaultdict(float)
    for path, s in own.items():
        tops[path.split("/")[0]] += s
    if not tops:
        return Decision(None, 0.0, 0.0, [], {})
    ranked = sorted(tops.items(), key=lambda kv: kv[1], reverse=True)
    top, top_score = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    if top_score < MIN_SCORE or (runner and top_score < MARGIN * runner):
        return Decision(None, top_score, 0.0, [], dict(tops))
    children = sorted(((p, s) for p, s in own.items() if p.startswith(top + "/")), key=lambda kv: kv[1], reverse=True)
    path = top
    if children and children[0][1] >= CHILD_MIN and (len(children) == 1 or children[0][1] > children[1][1]):
        path = children[0][0]
    # Explanation: one entry per distinct word, the bill's own text first (it is the most convincing evidence).
    order = {"bill text": 0, "merchant": 1, "item": 2, "description": 3}
    found = [r for p in ([path] if path != top else []) + [top] + [c for c, _ in children if c != path] for r in evidence.get(p, [])]
    reasons, seen_terms = [], set()
    for r in sorted(found, key=lambda r: order.get(r.split(":")[0], 9)):
        term = r.split(": ", 1)[1].strip("'")
        if term in seen_terms or any(term in t or t in term for t in seen_terms):
            continue  # "water" adds nothing after "water authority"
        seen_terms.add(term)
        reasons.append(r)
    confidence = round(min(0.95, 0.5 + top_score / 20), 2)
    return Decision(path, top_score, confidence, reasons[:6], dict(tops))

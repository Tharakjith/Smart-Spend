"""Exact decimal money helpers. Floats are rejected everywhere money is handled."""
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

# ISO 4217 minor units for currencies we expect; unknown codes default to 2.
MINOR_UNITS = {"JPY": 0, "KRW": 0, "VND": 0, "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3}
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "AED": "AED "}

ZERO = Decimal("0")


class MoneyError(ValueError):
    pass


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, float):
        # Floats cannot represent most decimal amounts; refuse instead of silently rounding.
        raise MoneyError("Monetary values must not be floats; pass a string or Decimal")
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "").strip()
        if not cleaned:
            raise MoneyError("Empty amount")
        try:
            d = Decimal(cleaned)
        except InvalidOperation as exc:
            raise MoneyError(f"Invalid amount: {value!r}") from exc
    else:
        raise MoneyError(f"Unsupported amount type: {type(value).__name__}")
    if not d.is_finite():
        raise MoneyError("Amount must be finite")
    return d


def quantize(amount, currency: str = "INR") -> Decimal:
    d = to_decimal(amount)
    exp = MINOR_UNITS.get(currency.upper(), 2)
    return d.quantize(Decimal(1).scaleb(-exp), rounding=ROUND_HALF_EVEN)


def money_sum(values, currency: str = "INR") -> Decimal:
    total = ZERO
    for v in values:
        if v is None:
            continue
        total += to_decimal(v)
    return quantize(total, currency)


def fmt(amount, currency: str = "INR") -> str:
    q = quantize(amount, currency)
    sym = CURRENCY_SYMBOLS.get(currency.upper(), currency.upper() + " ")
    return f"{sym}{q:,}"


def is_valid_currency(code: str) -> bool:
    return isinstance(code, str) and len(code) == 3 and code.isalpha() and code.isupper()

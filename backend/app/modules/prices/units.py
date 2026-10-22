"""Unit normalisation so prices are only compared across compatible units (mass/volume/count)."""
from decimal import Decimal

UNITS = {
    "kg": ("mass", Decimal("1")),
    "kgs": ("mass", Decimal("1")),
    "g": ("mass", Decimal("0.001")),
    "gm": ("mass", Decimal("0.001")),
    "gms": ("mass", Decimal("0.001")),
    "gram": ("mass", Decimal("0.001")),
    "grams": ("mass", Decimal("0.001")),
    "mg": ("mass", Decimal("0.000001")),
    "l": ("volume", Decimal("1")),
    "ltr": ("volume", Decimal("1")),
    "litre": ("volume", Decimal("1")),
    "liter": ("volume", Decimal("1")),
    "ml": ("volume", Decimal("0.001")),
    "pc": ("count", Decimal("1")),
    "pcs": ("count", Decimal("1")),
    "piece": ("count", Decimal("1")),
    "nos": ("count", Decimal("1")),
    "no": ("count", Decimal("1")),
    "unit": ("count", Decimal("1")),
    "units": ("count", Decimal("1")),
    "pack": ("count", Decimal("1")),
    "pkt": ("count", Decimal("1")),
    "dozen": ("count", Decimal("12")),
}
BASE_UNIT = {"mass": "kg", "volume": "l", "count": "unit"}


def normalize_quantity(quantity, unit: str | None) -> tuple[str | None, Decimal | None]:
    """Returns (dimension, quantity in base unit) or (None, None) when the unit is unknown or quantity missing."""
    if quantity is None or not unit:
        return None, None
    info = UNITS.get(unit.strip().lower().rstrip("."))
    if not info:
        return None, None
    dim, factor = info
    q = Decimal(quantity) * factor
    if q <= 0:
        return None, None
    return dim, q.quantize(Decimal("0.0001"))

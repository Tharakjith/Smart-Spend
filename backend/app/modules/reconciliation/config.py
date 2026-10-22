"""Matching configuration. Every value here is documented in docs/ARCHITECTURE.md §4 and can be overridden
per household through households.matching_config (only known keys are honoured)."""
import copy
from decimal import Decimal

DEFAULT_MATCHING_CONFIG: dict = {
    "date_window_days": 3,
    "refund_window_days": 90,
    "amount_abs_tolerance": "20",
    "amount_pct_tolerance": "5",
    "time_window_minutes": 120,
    "weights": {
        "shared_reference": 50,
        "invoice_number": 45,
        "order_id": 15,
        "amount_equal": 35,
        "amount_equals_remaining": 30,
        "amount_within_tolerance": 15,
        "amount_partial": 10,
        "amount_covers_multiple": 5,
        "refund_full": 30,
        "refund_partial": 15,
        "merchant_same": 25,
        "merchant_similar_high": 20,
        "merchant_similar_medium": 10,
        "date_same_day": 20,
        "date_one_day": 10,
        "date_far_penalty": -5,
        "time_close": 5,
        "time_far_penalty": -10,
        "items_overlap": 10,
        "already_allocated_penalty": -30,
    },
    "thresholds": {"high": 75, "medium": 55, "low": 35},
}


def matching_config(household) -> dict:
    cfg = copy.deepcopy(DEFAULT_MATCHING_CONFIG)
    override = (household.matching_config or {}) if household is not None else {}
    for key, value in override.items():
        if key in ("weights", "thresholds") and isinstance(value, dict):
            for k, v in value.items():
                if k in cfg[key] and isinstance(v, int):
                    cfg[key][k] = v
        elif key in cfg and not isinstance(cfg[key], dict):
            cfg[key] = value
    return cfg


def tolerance(cfg: dict, base_amount: Decimal) -> Decimal:
    abs_tol = Decimal(str(cfg["amount_abs_tolerance"]))
    pct_tol = Decimal(str(cfg["amount_pct_tolerance"])) / Decimal(100) * base_amount
    return max(abs_tol, pct_tol)

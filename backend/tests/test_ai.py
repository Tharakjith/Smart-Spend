"""AI is optional and advisory: off by default, opt-in per household, and unable to fabricate values."""
from app.modules.ai import provider


def test_ai_disabled_by_default_makes_no_calls(user, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "_call_json", lambda *a, **k: calls.append(a) or {})
    t = user.payment("99.00", "Unknown Vendor 77")
    assert t["category_name"] == "Other and Uncategorized"
    assert calls == []


def _enable(user, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ai_provider", "anthropic")
    monkeypatch.setattr(get_settings(), "ai_allow_document_sharing", True)
    assert user.patch(f"/households/{user.household_id}", {"ai_opt_in": True}).status_code == 200


def test_ai_category_only_when_enabled_and_opted_in(user, monkeypatch):
    _enable(user, monkeypatch)
    monkeypatch.setattr(provider, "_call_json", lambda *a, **k: {"category": "Gaming"})
    t = user.payment("1500.00", "Zorblax Arcade")
    assert t["category_name"] == "Gaming" and t["category_source"] == "ai"
    # deterministic rules still win: AI is not consulted for known merchants
    monkeypatch.setattr(provider, "_call_json", lambda *a, **k: {"category": "Gaming"})
    assert user.payment("200.00", "Swiggy")["category_name"] == "Food Delivery"


def test_ai_suggestions_must_appear_in_document_text(user, monkeypatch):
    from types import SimpleNamespace

    household = SimpleNamespace(ai_opt_in=True)
    _enable(user, monkeypatch)
    text = "CORNER CAFE\nCappuccino 180.00\nTOTAL DUE 1,250.00\nRef 7781"
    monkeypatch.setattr(
        provider,
        "_call_json",
        lambda *a, **k: {"merchant_name": "Corner Cafe", "date": "2026-10-18", "total": "1250.00", "currency": "INR", "invoice_number": "INV-999", "payment_reference": None},
    )
    out = provider.suggest_missing_fields(household, text, {"merchant_name": {"value": None}, "total": {"value": None}, "invoice_number": {"value": None}})
    assert out["merchant_name"]["value"] == "Corner Cafe" and out["merchant_name"]["source"] == "ai"
    assert out["total"]["value"] == "1250.00"  # matches the printed 1,250.00
    assert "invoice_number" not in out  # INV-999 is not in the text: discarded

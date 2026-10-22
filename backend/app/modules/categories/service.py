import re
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanonicalTransaction, Category, Merchant, UserRule
from app.modules.categories.defaults import DEFAULT_CATEGORIES, ITEM_KEYWORDS, UNCATEGORIZED


def seed_categories(db: Session, household_id: uuid.UUID) -> None:
    for name, (kind, fixed, color, subs) in DEFAULT_CATEGORIES.items():
        parent = Category(household_id=household_id, name=name, kind=kind, is_system=True, is_fixed=fixed, color=color)
        db.add(parent)
        db.flush()
        for sub in subs:
            db.add(Category(household_id=household_id, parent_id=parent.id, name=sub, kind=kind, is_system=True, is_fixed=fixed, color=color))
    db.flush()


class CategoryIndex:
    """Resolves "Parent/Child" paths to category ids for one household."""

    def __init__(self, db: Session, household_id: uuid.UUID):
        cats = db.scalars(select(Category).where(Category.household_id == household_id, Category.is_archived.is_(False))).all()
        self.by_id = {c.id: c for c in cats}
        self.paths: dict[str, uuid.UUID] = {}
        for c in cats:
            if c.parent_id is None:
                self.paths[c.name.lower()] = c.id
        for c in cats:
            if c.parent_id is not None and c.parent_id in self.by_id:
                self.paths[f"{self.by_id[c.parent_id].name}/{c.name}".lower()] = c.id

    def resolve(self, path: str) -> uuid.UUID | None:
        cid = self.paths.get(path.lower())
        if cid is None and "/" in path:
            cid = self.paths.get(path.split("/", 1)[0].lower())
        return cid

    def subtree(self, category_id: uuid.UUID) -> set[uuid.UUID]:
        ids = {category_id}
        changed = True
        while changed:
            changed = False
            for c in self.by_id.values():
                if c.parent_id in ids and c.id not in ids:
                    ids.add(c.id)
                    changed = True
        return ids

    def top_level(self, category_id: uuid.UUID | None) -> uuid.UUID | None:
        c = self.by_id.get(category_id) if category_id else None
        while c is not None and c.parent_id is not None and c.parent_id in self.by_id:
            c = self.by_id[c.parent_id]
        return c.id if c else None


def _rule_matches(rule: UserRule, value: str) -> bool:
    v = (value or "").lower()
    p = rule.pattern.lower()
    if not v:
        return False
    if rule.operator == "contains":
        return p in v
    if rule.operator == "equals":
        return v.strip() == p.strip()
    if rule.operator == "starts_with":
        return v.startswith(p)
    if rule.operator == "regex":
        try:
            return re.search(rule.pattern, value or "", re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def _keyword_hit(text: str, table: dict[str, str]) -> str | None:
    t = f" {text.lower()} "
    # Longest keyword first so "income tax" beats "tax", "water bill" beats "bill".
    for kw in sorted(table, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", t):
            return table[kw]
    return None


def categorize(
    db: Session,
    household_id: uuid.UUID,
    *,
    description: str = "",
    merchant_name: str = "",
    merchant_id: uuid.UUID | None = None,
    counterparty_name: str = "",
    item_names: list[str] | None = None,
    tx_type: str = "expense",
    document_text: str = "",
) -> dict:
    """Returns {"category_id", "source", "confidence", "set_type", "reasons"} following the documented priority order:
    user rules -> confirmed merchant mappings -> evidence scoring -> (optional AI) -> uncategorised."""
    idx = CategoryIndex(db, household_id)

    # 1. User-defined rules (lowest priority number first).
    rules = db.scalars(
        select(UserRule).where(UserRule.household_id == household_id, UserRule.is_active.is_(True)).order_by(UserRule.priority, UserRule.created_at)
    ).all()
    fields = {"description": description, "merchant": merchant_name, "counterparty": counterparty_name, "item": " | ".join(item_names or [])}
    for rule in rules:
        if _rule_matches(rule, fields.get(rule.field, "")):
            return {"category_id": rule.category_id, "source": "user_rule", "confidence": 1.0, "set_type": rule.set_type, "rule_id": str(rule.id)}

    if tx_type == "expense" or tx_type == "refund":
        # 2. Previously confirmed merchant mappings.
        if merchant_id:
            merchant = db.get(Merchant, merchant_id)
            if merchant and merchant.default_category_id:
                return {"category_id": merchant.default_category_id, "source": "merchant_default", "confidence": 0.95, "set_type": None}
            history = db.scalars(
                select(CanonicalTransaction.category_id).where(
                    CanonicalTransaction.household_id == household_id,
                    CanonicalTransaction.merchant_id == merchant_id,
                    CanonicalTransaction.category_source.in_(("manual", "confirmed", "user_rule")),
                    CanonicalTransaction.category_id.is_not(None),
                    CanonicalTransaction.status == "active",
                )
            ).all()
            if history:
                cid, n = Counter(history).most_common(1)[0]
                if n / len(history) >= 0.6:
                    return {"category_id": cid, "source": "merchant_history", "confidence": 0.9, "set_type": None}

        # 3-4. Evidence scoring over merchant, description, line items and the bill's own text.
        decided = _score(idx, "expense", merchant_name, description, item_names, document_text)
        if decided:
            return decided

        # 5. Optional AI classification is applied by callers that opt in (never required).
        # 6. Uncategorised.
        return {"category_id": idx.resolve(UNCATEGORIZED), "source": "uncategorized", "confidence": 0.0, "set_type": None, "reasons": []}

    if tx_type == "income":
        decided = _score(idx, "income", merchant_name or counterparty_name, description, None, document_text)
        if decided:
            return decided
        return {"category_id": idx.resolve("Other Income"), "source": "uncategorized", "confidence": 0.0, "set_type": None, "reasons": []}

    return {"category_id": None, "source": "none", "confidence": 0.0, "set_type": None, "reasons": []}


def _score(idx: "CategoryIndex", kind: str, merchant: str, description: str, items: list[str] | None, document_text: str) -> dict | None:
    from app.modules.categories.classifier import MEDIUM, STRONG, classify

    tops = {c.name for c in idx.by_id.values() if c.parent_id is None and c.kind == kind}
    # Item keywords (rice, detergent, paracetamol...) only count when they appear as line items.
    item_terms: dict[str, dict[str, float]] = {}
    for term, path in ITEM_KEYWORDS.items():
        item_terms.setdefault(path, {})[term] = MEDIUM
    # Categories the household created take part through their own names ("Pet Care", "Kids' School").
    extra: dict[str, dict[str, float]] = {}
    for c in idx.by_id.values():
        if not c.is_system and c.kind == kind:
            parent = idx.by_id.get(c.parent_id) if c.parent_id else None
            path = f"{parent.name}/{c.name}" if parent else c.name
            extra.setdefault(path, {})[c.name.lower()] = STRONG
            tops.add(parent.name if parent else c.name)
    decision = classify(
        merchant=merchant or "",
        description=description or "",
        items=items or [],
        document_text=document_text or "",
        allowed_paths=tops,
        extra_terms=extra,
        item_terms=item_terms,
    )
    if not decision.path:
        return None
    cid = idx.resolve(decision.path)
    if cid is None or idx.by_id[cid].kind != kind:
        return None
    return {"category_id": cid, "source": "keyword", "confidence": decision.confidence, "set_type": None, "reasons": decision.reasons}


def categorize_item(idx: CategoryIndex, name: str) -> uuid.UUID | None:
    hit = _keyword_hit(name, ITEM_KEYWORDS)
    return idx.resolve(hit) if hit else None

"""Accounts, categories, user rules, merchants and aliases."""
import re
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import case, func, select

from app.core.deps import Ctx, admin_ctx, get_ctx, writer_ctx
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import quantize
from app.models import Account, CanonicalTransaction, Category, Merchant, MerchantAlias, TransactionLineItem, UserRule
from app.models.finance import ACCOUNT_TYPES, TRANSACTION_TYPES
from app.modules.categories.service import categorize
from app.modules.common import Money, OptMoney, Schema, audit, snapshot
from app.modules.merchants.normalize import normalize_merchant
from app.modules.merchants.service import add_alias

router = APIRouter(tags=["catalog"])


# ---------------------------------------------------------------- accounts
class AccountIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    type: str
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    opening_balance: Money = Decimal("0")
    opening_balance_date: date | None = None
    institution: str = Field(default="", max_length=120)
    masked_number: str = Field(default="", max_length=4, pattern=r"^\d{0,4}$")
    upi_handle: str = Field(default="", max_length=120)
    credit_limit: OptMoney = None
    statement_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)


class AccountPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    opening_balance: Money | None = None
    opening_balance_date: date | None = None
    institution: str | None = None
    masked_number: str | None = Field(default=None, max_length=4, pattern=r"^\d{0,4}$")
    upi_handle: str | None = None
    is_archived: bool | None = None
    credit_limit: OptMoney = None
    statement_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)


class AccountOut(Schema):
    id: uuid.UUID
    name: str
    type: str
    currency: str
    opening_balance: Money
    opening_balance_date: date | None
    institution: str
    masked_number: str
    upi_handle: str
    is_archived: bool
    credit_limit: OptMoney = None
    statement_day: int | None = None
    due_day: int | None = None


def _check_card_fields(acc_type: str, data: dict) -> None:
    if any(data.get(k) is not None for k in ("credit_limit", "statement_day", "due_day")) and acc_type != "credit_card":
        raise ValidationFailed("Credit limit, statement day and due day apply to credit cards only")
    if data.get("credit_limit") is not None and data["credit_limit"] < 0:
        raise ValidationFailed("Credit limit can't be negative")


def account_balance(ctx: Ctx, acc: Account) -> dict:
    """Opening balance plus active ledger movements in/out of this account (merged duplicates excluded)."""
    ct = CanonicalTransaction
    signed = case(
        (ct.type.in_([t for t, d in TRANSACTION_TYPES.items() if d == "in"]), ct.cash_amount),
        (ct.type.in_([t for t, d in TRANSACTION_TYPES.items() if d == "out"]), -ct.cash_amount),
        else_=-ct.cash_amount,  # internal transfer: leaves the source account
    )
    q = select(func.coalesce(func.sum(signed), 0)).where(ct.household_id == ctx.household_id, ct.account_id == acc.id, ct.status == "active", ct.currency == acc.currency)
    if acc.opening_balance_date:
        q = q.where(ct.occurred_on >= acc.opening_balance_date)
    flows = ctx.db.scalar(q) or Decimal("0")
    q_in = select(func.coalesce(func.sum(ct.cash_amount), 0)).where(
        ct.household_id == ctx.household_id, ct.to_account_id == acc.id, ct.status == "active", ct.type.in_(("transfer", "credit_card_payment")), ct.currency == acc.currency
    )
    if acc.opening_balance_date:
        q_in = q_in.where(ct.occurred_on >= acc.opening_balance_date)
    transfers_in = ctx.db.scalar(q_in) or Decimal("0")
    balance = quantize(Decimal(acc.opening_balance) + Decimal(flows) + Decimal(transfers_in), acc.currency)
    # For credit cards, a negative balance means amount owed.
    return {"account_id": str(acc.id), "currency": acc.currency, "balance": format(balance, "f"), "as_of": date.today().isoformat()}


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(include_archived: bool = False, ctx: Ctx = Depends(get_ctx)):
    q = select(Account).where(Account.household_id == ctx.household_id).order_by(Account.name)
    if not include_archived:
        q = q.where(Account.is_archived.is_(False))
    return ctx.db.scalars(q).all()


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, ctx: Ctx = Depends(writer_ctx)):
    if body.type not in ACCOUNT_TYPES:
        raise ValidationFailed(f"type must be one of {', '.join(ACCOUNT_TYPES)}")
    _check_card_fields(body.type, body.model_dump())
    acc = Account(household_id=ctx.household_id, **body.model_dump())
    acc.opening_balance = quantize(acc.opening_balance, acc.currency)
    if acc.credit_limit is not None:
        acc.credit_limit = quantize(acc.credit_limit, acc.currency)
    ctx.db.add(acc)
    ctx.db.flush()
    audit(ctx, "create", "account", acc.id, None, snapshot(acc))
    ctx.db.commit()
    return acc


def _get_account(ctx: Ctx, account_id: uuid.UUID) -> Account:
    acc = ctx.db.get(Account, account_id)
    if acc is None or acc.household_id != ctx.household_id:
        raise NotFound("Account not found")
    return acc


@router.get("/accounts/{account_id}/balance")
def get_balance(account_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    return account_balance(ctx, _get_account(ctx, account_id))


@router.get("/accounts-balances")
def all_balances(ctx: Ctx = Depends(get_ctx)):
    accs = ctx.db.scalars(select(Account).where(Account.household_id == ctx.household_id, Account.is_archived.is_(False))).all()
    return [account_balance(ctx, a) for a in accs]


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: uuid.UUID, body: AccountPatch, ctx: Ctx = Depends(writer_ctx)):
    acc = _get_account(ctx, account_id)
    _check_card_fields(acc.type, body.model_dump(exclude_unset=True))
    before = snapshot(acc)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in ("opening_balance", "credit_limit") and v is not None:
            v = quantize(v, acc.currency)
        setattr(acc, k, v)
    audit(ctx, "update", "account", acc.id, before, snapshot(acc))
    ctx.db.commit()
    return acc


@router.delete("/accounts/{account_id}")
def delete_account(account_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    acc = _get_account(ctx, account_id)
    used = ctx.db.scalar(select(func.count()).select_from(CanonicalTransaction).where(CanonicalTransaction.account_id == acc.id))
    if used:
        acc.is_archived = True  # keep history intact
        audit(ctx, "archive", "account", acc.id)
        ctx.db.commit()
        return {"ok": True, "archived": True}
    audit(ctx, "delete", "account", acc.id, snapshot(acc), None)
    ctx.db.delete(acc)
    ctx.db.commit()
    return {"ok": True, "archived": False}


# ---------------------------------------------------------------- categories
class CategoryIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    kind: str = Field(default="expense", pattern="^(expense|income|other)$")
    is_fixed: bool = False
    color: str = Field(default="", max_length=16)
    icon: str = Field(default="", max_length=40)


class CategoryPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_fixed: bool | None = None
    color: str | None = None
    icon: str | None = None
    is_archived: bool | None = None


class CategoryOut(Schema):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    kind: str
    is_system: bool
    is_fixed: bool
    color: str
    icon: str
    is_archived: bool


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(ctx: Ctx = Depends(get_ctx)):
    return ctx.db.scalars(select(Category).where(Category.household_id == ctx.household_id).order_by(Category.kind, Category.name)).all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, ctx: Ctx = Depends(writer_ctx)):
    if body.parent_id:
        parent = ctx.db.get(Category, body.parent_id)
        if parent is None or parent.household_id != ctx.household_id:
            raise NotFound("Parent category not found")
        if parent.parent_id is not None:
            grand = ctx.db.get(Category, parent.parent_id)
            if grand and grand.parent_id is not None:
                raise ValidationFailed("Categories can be nested at most three levels deep")
    exists = ctx.db.scalars(
        select(Category).where(
            Category.household_id == ctx.household_id,
            Category.parent_id.is_(None) if body.parent_id is None else Category.parent_id == body.parent_id,
            func.lower(Category.name) == body.name.lower(),
        )
    ).first()
    if exists:
        raise Conflict("A category with this name already exists here")
    cat = Category(household_id=ctx.household_id, **body.model_dump())
    ctx.db.add(cat)
    ctx.db.flush()
    audit(ctx, "create", "category", cat.id, None, snapshot(cat))
    ctx.db.commit()
    return cat


def _get_category(ctx: Ctx, cid: uuid.UUID) -> Category:
    c = ctx.db.get(Category, cid)
    if c is None or c.household_id != ctx.household_id:
        raise NotFound("Category not found")
    return c


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: uuid.UUID, body: CategoryPatch, ctx: Ctx = Depends(writer_ctx)):
    c = _get_category(ctx, category_id)
    before = snapshot(c)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    audit(ctx, "update", "category", c.id, before, snapshot(c))
    ctx.db.commit()
    return c


@router.delete("/categories/{category_id}")
def delete_category(category_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    c = _get_category(ctx, category_id)
    if c.is_system:
        raise Conflict("System categories can be archived but not deleted", code="system_category")
    used = ctx.db.scalar(select(func.count()).select_from(CanonicalTransaction).where(CanonicalTransaction.category_id == c.id))
    used += ctx.db.scalar(select(func.count()).select_from(TransactionLineItem).where(TransactionLineItem.category_id == c.id))
    children = ctx.db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == c.id))
    if used or children:
        c.is_archived = True
        audit(ctx, "archive", "category", c.id)
        ctx.db.commit()
        return {"ok": True, "archived": True}
    audit(ctx, "delete", "category", c.id, snapshot(c), None)
    ctx.db.delete(c)
    ctx.db.commit()
    return {"ok": True, "archived": False}


# ---------------------------------------------------------------- user rules
class RuleIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    priority: int = Field(default=100, ge=0, le=10000)
    field: str = Field(pattern="^(description|merchant|item|counterparty)$")
    operator: str = Field(pattern="^(contains|equals|starts_with|regex)$")
    pattern: str = Field(min_length=1, max_length=300)
    category_id: uuid.UUID | None = None
    set_type: str | None = None
    is_active: bool = True


class RuleOut(RuleIn):
    id: uuid.UUID


class RuleTestIn(Schema):
    description: str = ""
    merchant: str = ""
    items: list[str] = []
    type: str = "expense"


def _validate_rule(ctx: Ctx, body: RuleIn) -> None:
    if body.category_id is None and body.set_type is None:
        raise ValidationFailed("A rule must set a category or a transaction type")
    if body.category_id:
        _get_category(ctx, body.category_id)
    if body.set_type and body.set_type not in TRANSACTION_TYPES:
        raise ValidationFailed("Unknown transaction type")
    if body.operator == "regex":
        try:
            re.compile(body.pattern)
        except re.error as exc:
            raise ValidationFailed(f"Invalid regular expression: {exc}")


@router.get("/rules", response_model=list[RuleOut])
def list_rules(ctx: Ctx = Depends(get_ctx)):
    return ctx.db.scalars(select(UserRule).where(UserRule.household_id == ctx.household_id).order_by(UserRule.priority, UserRule.created_at)).all()


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, ctx: Ctx = Depends(writer_ctx)):
    _validate_rule(ctx, body)
    r = UserRule(household_id=ctx.household_id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.flush()
    audit(ctx, "create", "rule", r.id, None, snapshot(r))
    ctx.db.commit()
    return r


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RuleIn, ctx: Ctx = Depends(writer_ctx)):
    r = ctx.db.get(UserRule, rule_id)
    if r is None or r.household_id != ctx.household_id:
        raise NotFound("Rule not found")
    _validate_rule(ctx, body)
    before = snapshot(r)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit(ctx, "update", "rule", r.id, before, snapshot(r))
    ctx.db.commit()
    return r


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    r = ctx.db.get(UserRule, rule_id)
    if r is None or r.household_id != ctx.household_id:
        raise NotFound("Rule not found")
    audit(ctx, "delete", "rule", r.id, snapshot(r), None)
    ctx.db.delete(r)
    ctx.db.commit()
    return {"ok": True}


@router.post("/rules/test")
def test_rules(body: RuleTestIn, ctx: Ctx = Depends(get_ctx)):
    from app.modules.merchants.service import find_merchant

    m = find_merchant(ctx.db, ctx.household_id, body.merchant) if body.merchant else None
    res = categorize(ctx.db, ctx.household_id, description=body.description, merchant_name=body.merchant, merchant_id=m.id if m else None, item_names=body.items, tx_type=body.type)
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in res.items()}


# ---------------------------------------------------------------- merchants
class MerchantIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    default_category_id: uuid.UUID | None = None
    upi_id: str = Field(default="", max_length=120)


class MerchantPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    default_category_id: uuid.UUID | None = None
    upi_id: str | None = None


class AliasIn(Schema):
    alias: str = Field(min_length=1, max_length=200)


@router.get("/merchants")
def list_merchants(q: str | None = None, limit: int = Query(200, le=500), ctx: Ctx = Depends(get_ctx)):
    stmt = select(Merchant).where(Merchant.household_id == ctx.household_id).order_by(Merchant.name).limit(limit)
    if q:
        stmt = stmt.where(Merchant.name.ilike(f"%{q}%"))
    merchants = ctx.db.scalars(stmt).all()
    aliases = ctx.db.scalars(select(MerchantAlias).where(MerchantAlias.household_id == ctx.household_id)).all()
    by_m: dict = {}
    for a in aliases:
        by_m.setdefault(a.merchant_id, []).append({"id": str(a.id), "alias": a.alias, "source": a.source})
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "normalized_name": m.normalized_name,
            "default_category_id": str(m.default_category_id) if m.default_category_id else None,
            "upi_id": m.upi_id,
            "aliases": by_m.get(m.id, []),
        }
        for m in merchants
    ]


@router.post("/merchants", status_code=201)
def create_merchant(body: MerchantIn, ctx: Ctx = Depends(writer_ctx)):
    norm = normalize_merchant(body.name)
    if not norm:
        raise ValidationFailed("Merchant name must contain letters or digits")
    if ctx.db.scalars(select(Merchant).where(Merchant.household_id == ctx.household_id, Merchant.normalized_name == norm)).first():
        raise Conflict("A merchant with an equivalent name already exists")
    m = Merchant(household_id=ctx.household_id, name=body.name.strip(), normalized_name=norm, default_category_id=body.default_category_id, upi_id=body.upi_id)
    ctx.db.add(m)
    ctx.db.flush()
    audit(ctx, "create", "merchant", m.id, None, snapshot(m))
    ctx.db.commit()
    return {"id": str(m.id)}


@router.patch("/merchants/{merchant_id}")
def update_merchant(merchant_id: uuid.UUID, body: MerchantPatch, ctx: Ctx = Depends(writer_ctx)):
    m = ctx.db.get(Merchant, merchant_id)
    if m is None or m.household_id != ctx.household_id:
        raise NotFound("Merchant not found")
    before = snapshot(m)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    audit(ctx, "update", "merchant", m.id, before, snapshot(m))
    ctx.db.commit()
    return {"ok": True}


@router.post("/merchants/{merchant_id}/aliases", status_code=201)
def create_alias(merchant_id: uuid.UUID, body: AliasIn, ctx: Ctx = Depends(writer_ctx)):
    m = ctx.db.get(Merchant, merchant_id)
    if m is None or m.household_id != ctx.household_id:
        raise NotFound("Merchant not found")
    norm = normalize_merchant(body.alias)
    existing = ctx.db.scalars(select(MerchantAlias).where(MerchantAlias.household_id == ctx.household_id, MerchantAlias.normalized_alias == norm)).first()
    if existing and existing.merchant_id != m.id:
        raise Conflict("This alias already belongs to another merchant", code="alias_taken")
    add_alias(ctx.db, ctx.household_id, m.id, body.alias, "user")
    audit(ctx, "add_alias", "merchant", m.id, None, {"alias": body.alias})
    ctx.db.commit()
    return {"ok": True}


@router.delete("/merchant-aliases/{alias_id}")
def delete_alias(alias_id: uuid.UUID, ctx: Ctx = Depends(writer_ctx)):
    a = ctx.db.get(MerchantAlias, alias_id)
    if a is None or a.household_id != ctx.household_id:
        raise NotFound("Alias not found")
    audit(ctx, "delete_alias", "merchant", a.merchant_id, {"alias": a.alias}, None)
    ctx.db.delete(a)
    ctx.db.commit()
    return {"ok": True}

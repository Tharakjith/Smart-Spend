import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Merchant, MerchantAlias
from app.modules.merchants.normalize import normalize_merchant


def find_merchant(db: Session, household_id: uuid.UUID, raw_name: str) -> Merchant | None:
    norm = normalize_merchant(raw_name)
    if not norm:
        return None
    alias = db.scalars(select(MerchantAlias).where(MerchantAlias.household_id == household_id, MerchantAlias.normalized_alias == norm)).first()
    if alias:
        return db.get(Merchant, alias.merchant_id)
    return db.scalars(select(Merchant).where(Merchant.household_id == household_id, Merchant.normalized_name == norm)).first()


def resolve_merchant(db: Session, household_id: uuid.UUID, raw_name: str | None, *, create: bool = True) -> Merchant | None:
    """Find by confirmed alias or normalised name; optionally create. Safe under concurrent creation."""
    if not raw_name or not raw_name.strip():
        return None
    found = find_merchant(db, household_id, raw_name)
    if found or not create:
        return found
    norm = normalize_merchant(raw_name)
    if not norm:
        return None
    stmt = (
        insert(Merchant)
        .values(id=uuid.uuid4(), household_id=household_id, name=raw_name.strip()[:200], normalized_name=norm, upi_id="")
        .on_conflict_do_nothing(index_elements=["household_id", "normalized_name"])
    )
    db.execute(stmt)
    return db.scalars(select(Merchant).where(Merchant.household_id == household_id, Merchant.normalized_name == norm)).first()


def add_alias(db: Session, household_id: uuid.UUID, merchant_id: uuid.UUID, alias: str, source: str = "user") -> bool:
    norm = normalize_merchant(alias)
    if not norm:
        return False
    target = db.get(Merchant, merchant_id)
    if target and target.normalized_name == norm:
        return False
    stmt = (
        insert(MerchantAlias)
        .values(id=uuid.uuid4(), household_id=household_id, merchant_id=merchant_id, alias=alias.strip()[:200], normalized_alias=norm, source=source)
        .on_conflict_do_nothing(index_elements=["household_id", "normalized_alias"])
        .returning(MerchantAlias.id)
    )
    return db.execute(stmt).scalar() is not None


def merchants_are_aliases(db: Session, household_id: uuid.UUID, name_a: str, name_b: str) -> bool:
    """True when both names resolve to the same known merchant via confirmed aliases."""
    a = find_merchant(db, household_id, name_a)
    b = find_merchant(db, household_id, name_b)
    return a is not None and b is not None and a.id == b.id

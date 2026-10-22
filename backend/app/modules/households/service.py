from sqlalchemy.orm import Session

from app.models import Account, Household, HouseholdMember, User
from app.modules.categories.service import seed_categories


def create_household(db: Session, owner: User, name: str, base_currency: str = "INR", timezone: str = "Asia/Kolkata", is_demo: bool = False) -> Household:
    h = Household(name=name, base_currency=base_currency, timezone=timezone, is_demo=is_demo)
    db.add(h)
    db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=owner.id, role="owner"))
    seed_categories(db, h.id)
    db.add(Account(household_id=h.id, name="Cash", type="cash", currency=base_currency))
    db.flush()
    return h

"""Data export and account deletion (privacy workflows)."""
import io
import json
import zipfile
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import func, select

from app.core.db import utcnow
from app.core.deps import AuthUser, Ctx, get_auth_user, get_ctx
from app.core.errors import Conflict, Unauthorized
from app.core.security import verify_password
from app.core.storage import get_storage
from app.models import (
    Account,
    AuditLog,
    Budget,
    CanonicalTransaction,
    Category,
    Counterparty,
    CreditCardBillPayment,
    CreditCardStatement,
    Document,
    Household,
    HouseholdMember,
    Loan,
    LoanRepayment,
    Merchant,
    MerchantAlias,
    ReconciliationAllocation,
    ReconciliationMatch,
    RecurringExpense,
    SavingsGoal,
    SharedExpense,
    SharedExpenseParticipant,
    SourceRecord,
    StatementRow,
    TransactionLineItem,
    UserRule,
    UserSession,
)
from app.modules.common import Schema, snapshot

router = APIRouter(prefix="/me", tags=["privacy"])

EXPORT_MODELS = [
    Account, Category, Merchant, MerchantAlias, Counterparty, UserRule, CanonicalTransaction, TransactionLineItem, SourceRecord,
    ReconciliationMatch, ReconciliationAllocation, StatementRow, Loan, LoanRepayment, SharedExpense, SharedExpenseParticipant,
    Budget, SavingsGoal, RecurringExpense, CreditCardStatement, CreditCardBillPayment,
]


@router.get("/export")
def export(ctx: Ctx = Depends(get_ctx), include_documents: bool = True):
    """A ZIP with every record of the selected household as JSON, plus the original uploaded documents."""
    ctx.require("admin")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", f"SmartSpend export of '{ctx.household.name}' generated {utcnow().isoformat()} by {ctx.user.email}.\nAmounts are decimal strings in each record's currency.\n")
        z.writestr("household.json", json.dumps(snapshot(ctx.household), indent=2))
        for model in EXPORT_MODELS:
            rows = ctx.db.scalars(select(model).where(model.household_id == ctx.household_id)).all()
            z.writestr(f"{model.__tablename__}.json", json.dumps([snapshot(r) for r in rows], indent=2, default=str))
        docs = ctx.db.scalars(select(Document).where(Document.household_id == ctx.household_id)).all()
        z.writestr("documents.json", json.dumps([snapshot(d, ["id", "original_filename", "content_type", "size_bytes", "sha256", "status", "doc_kind", "created_at"]) for d in docs], indent=2))
        if include_documents:
            for d in docs:
                try:
                    z.writestr(f"documents/{d.id}_{d.original_filename}", get_storage().get(d.storage_key))
                except Exception:
                    z.writestr(f"documents/{d.id}.MISSING.txt", "File could not be read from storage")
    ctx.db.add(AuditLog(household_id=ctx.household_id, actor_id=ctx.user.id, action="data_export", entity_type="household", entity_id=str(ctx.household_id), ip=ctx.ip))
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="smartspend-export-{date.today()}.zip"'})


class DeleteIn(Schema):
    password: str = Field(min_length=1)
    confirm: str = Field(description='Type "DELETE" to confirm')


@router.delete("")
def delete_account(body: DeleteIn, auth: AuthUser = Depends(get_auth_user)):
    """Deletes the user. Households where they are the only member are deleted with all data and files.
    Households shared with others are kept if another owner exists; otherwise deletion is refused."""
    from app.core.db import SessionLocal

    if body.confirm != "DELETE":
        raise Conflict('Type "DELETE" to confirm', code="confirmation_required")
    if not verify_password(body.password, auth.user.password_hash):
        raise Unauthorized("Password is incorrect", code="invalid_credentials")
    with SessionLocal() as db:
        user = db.get(type(auth.user), auth.user.id)
        memberships = db.scalars(select(HouseholdMember).where(HouseholdMember.user_id == user.id)).all()
        to_delete = []
        for m in memberships:
            others = db.scalar(select(func.count()).select_from(HouseholdMember).where(HouseholdMember.household_id == m.household_id, HouseholdMember.user_id != user.id))
            if others == 0:
                to_delete.append(m.household_id)
            elif m.role == "owner":
                other_owners = db.scalar(
                    select(func.count()).select_from(HouseholdMember).where(HouseholdMember.household_id == m.household_id, HouseholdMember.user_id != user.id, HouseholdMember.role == "owner")
                )
                if not other_owners:
                    raise Conflict("Make someone else an owner of your shared workspaces before deleting your account", code="last_owner")
        storage = get_storage()
        for hid in to_delete:
            for d in db.scalars(select(Document).where(Document.household_id == hid)).all():
                try:
                    storage.delete(d.storage_key)
                except Exception:
                    pass
            db.delete(db.get(Household, hid))
        for s in db.scalars(select(UserSession).where(UserSession.user_id == user.id)).all():
            s.revoked_at = utcnow()
        db.add(AuditLog(actor_id=None, action="account_deleted", entity_type="user", entity_id=str(user.id)))
        db.delete(user)
        db.commit()
    return {"ok": True, "deleted_households": [str(h) for h in to_delete]}

from fastapi import APIRouter, Depends, Query

from app.core.deps import Ctx, get_ctx
from app.modules.analytics import service as svc

router = APIRouter(tags=["analytics"])

MONTH = Query(None, pattern=r"^\d{4}-\d{2}$")


@router.get("/dashboard/summary")
def dashboard_summary(month: str | None = MONTH, ctx: Ctx = Depends(get_ctx)):
    return svc.dashboard(ctx, month)


@router.get("/analytics/trend")
def trend(months: int = Query(12, ge=1, le=36), end_month: str | None = MONTH, ctx: Ctx = Depends(get_ctx)):
    return svc.monthly_trend(ctx.db, ctx.household_id, ctx.household.base_currency, months, end_month)


@router.get("/analytics/categories")
def categories(month: str | None = MONTH, level: str = Query("top", pattern="^(top|leaf)$"), ctx: Ctx = Depends(get_ctx)):
    s, e = svc.month_bounds(month)
    return svc.category_breakdown(ctx.db, ctx.household_id, s, e, ctx.household.base_currency, level)


@router.get("/analytics/daily")
def daily(month: str | None = MONTH, ctx: Ctx = Depends(get_ctx)):
    s, e = svc.month_bounds(month)
    return svc.daily_spending(ctx.db, ctx.household_id, s, e, ctx.household.base_currency)


@router.get("/analytics/merchants")
def merchants(month: str | None = MONTH, limit: int = Query(10, le=50), ctx: Ctx = Depends(get_ctx)):
    s, e = svc.month_bounds(month)
    return svc.top_merchants(ctx.db, ctx.household_id, s, e, ctx.household.base_currency, limit)


@router.get("/analytics/payment-methods")
def payment_methods(month: str | None = MONTH, ctx: Ctx = Depends(get_ctx)):
    s, e = svc.month_bounds(month)
    return svc.payment_methods(ctx.db, ctx.household_id, s, e, ctx.household.base_currency)


@router.get("/analytics/fixed-variable")
def fixed_variable(month: str | None = MONTH, ctx: Ctx = Depends(get_ctx)):
    s, e = svc.month_bounds(month)
    return svc.fixed_vs_variable(ctx.db, ctx.household_id, s, e, ctx.household.base_currency)


@router.get("/analytics/budget-vs-actual")
def budget_vs_actual(ctx: Ctx = Depends(get_ctx)):
    return svc.budget_status(ctx.db, ctx.household_id, ctx.household.base_currency)

"""Item price history from confirmed receipts. Prices are compared only within the same normalised
product name and unit dimension (mass/volume/count); every observation cites its source receipt."""
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import Ctx, get_ctx
from app.core.money import quantize
from app.models import CanonicalTransaction, Merchant, SourceRecord, TransactionLineItem
from app.modules.prices.units import BASE_UNIT

router = APIRouter(prefix="/prices", tags=["prices"])

INCREASE_FLAG = Decimal("0.15")


def _observations(ctx: Ctx, name: str):
    q = (
        select(TransactionLineItem, CanonicalTransaction)
        .join(CanonicalTransaction, CanonicalTransaction.id == TransactionLineItem.transaction_id)
        .where(
            TransactionLineItem.household_id == ctx.household_id,
            TransactionLineItem.normalized_name == name,
            CanonicalTransaction.status == "active",
        )
        .order_by(CanonicalTransaction.occurred_on)
    )
    return ctx.db.execute(q).all()


@router.get("/search")
def search(ctx: Ctx = Depends(get_ctx), q: str = Query("", max_length=100), limit: int = Query(50, le=200)):
    stmt = (
        select(TransactionLineItem.normalized_name, func.count(), func.max(TransactionLineItem.name))
        .join(CanonicalTransaction, CanonicalTransaction.id == TransactionLineItem.transaction_id)
        .where(TransactionLineItem.household_id == ctx.household_id, CanonicalTransaction.status == "active", TransactionLineItem.normalized_name != "")
        .group_by(TransactionLineItem.normalized_name)
        .order_by(func.count().desc())
        .limit(limit)
    )
    if q:
        stmt = stmt.where(TransactionLineItem.normalized_name.ilike(f"%{q.lower()}%"))
    return [{"product": n, "display_name": d, "purchases": c, "repeated": c > 1} for n, c, d in ctx.db.execute(stmt).all()]


@router.get("/history")
def history(product: str, ctx: Ctx = Depends(get_ctx)):
    rows = _observations(ctx, product.lower())
    merchants = {m.id: m.name for m in ctx.db.scalars(select(Merchant).where(Merchant.household_id == ctx.household_id)).all()}
    docs = {}
    ids = [t.id for _, t in rows]
    if ids:
        for s in ctx.db.scalars(select(SourceRecord).where(SourceRecord.canonical_transaction_id.in_(ids), SourceRecord.document_id.is_not(None))).all():
            docs[s.canonical_transaction_id] = str(s.document_id)
    by_dim: dict[str, list] = defaultdict(list)
    for li, t in rows:
        if li.line_total is None:
            continue
        if li.unit_dimension and li.base_quantity:
            dim, per = li.unit_dimension, Decimal(li.line_total) / Decimal(li.base_quantity)
        elif li.quantity:
            dim, per = "count", Decimal(li.line_total) / Decimal(li.quantity)
        else:
            dim, per = "unknown", None
        by_dim[dim].append(
            {
                "date": t.occurred_on.isoformat(),
                "merchant": merchants.get(t.merchant_id, ""),
                "item_name": li.name,
                "quantity": format(li.quantity, "f") if li.quantity is not None else None,
                "unit": li.unit,
                "line_total": format(Decimal(li.line_total), "f"),
                "unit_price": format(quantize(per, t.currency), "f") if per is not None else None,
                "price_unit": BASE_UNIT.get(dim) if dim != "unknown" else None,
                "currency": t.currency,
                "transaction_id": str(t.id),
                "document_id": docs.get(t.id),
            }
        )
    series = []
    for dim, obs in by_dim.items():
        flags = []
        prev = None
        for o in obs:
            if o["unit_price"] is not None and prev is not None and prev["unit_price"] is not None and prev["currency"] == o["currency"]:
                p0, p1 = Decimal(prev["unit_price"]), Decimal(o["unit_price"])
                if p0 > 0 and (p1 - p0) / p0 > INCREASE_FLAG:
                    flags.append({"date": o["date"], "from": prev["unit_price"], "to": o["unit_price"], "increase_pct": round(float((p1 - p0) / p0 * 100), 1), "merchant": o["merchant"]})
            prev = o
        by_merchant = defaultdict(list)
        for o in obs:
            if o["unit_price"] is not None:
                by_merchant[o["merchant"]].append(Decimal(o["unit_price"]))
        series.append(
            {
                "dimension": dim,
                "price_unit": BASE_UNIT.get(dim),
                "observations": obs,
                "unusual_increases": flags,
                "merchant_comparison": [
                    {"merchant": m, "observations": len(v), "latest_unit_price": format(v[-1], "f"), "lowest_unit_price": format(min(v), "f")} for m, v in by_merchant.items()
                ],
            }
        )
    return {"product": product, "series": series, "note": "Prices are compared only across compatible units; items without quantities are listed but not compared."}

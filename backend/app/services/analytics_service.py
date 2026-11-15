"""Deterministic multi-currency shopping analytics service (Section 6.8 & 8.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SupportedCurrency
from app.models.category import Category
from app.models.product import Product
from app.models.profile import Profile
from app.models.purchase import Purchase, PurchaseItem
from app.models.store import Store, StoreChain
from app.schemas.analytics import (
    CategorySpendingRow,
    CurrencySpendingSummary,
    HouseholdSpendingResponse,
    MonthlyTrendPoint,
    PriceChangeRow,
    StoreSpendingRow,
    TopProductRow,
)
from app.schemas.catalog import MacroGroup
from app.services.pricing_service import quantize_money


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


async def _load_macro_lookup(session: AsyncSession) -> dict[uuid.UUID, str]:
    cats = (await session.scalars(select(Category))).all()
    return {c.id: c.macro_group for c in cats}


def _resolve_item_macro(
    item: PurchaseItem,
    macro_lookup: dict[uuid.UUID, str],
) -> MacroGroup:
    if item.category_id_snapshot and item.category_id_snapshot in macro_lookup:
        return cast(MacroGroup, macro_lookup[item.category_id_snapshot])
    if item.parent_category_id_snapshot and item.parent_category_id_snapshot in macro_lookup:
        return cast(MacroGroup, macro_lookup[item.parent_category_id_snapshot])
    return "household"


async def get_spending_summary(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    currency: SupportedCurrency | None = None,
) -> list[CurrencySpendingSummary]:
    """Group spending strictly by currency; never sum different currencies together."""
    macro_lookup = await _load_macro_lookup(session)

    p_stmt = select(Purchase).where(Purchase.user_id == user_id)
    if date_from is not None:
        p_stmt = p_stmt.where(Purchase.purchase_date >= date_from)
    if date_to is not None:
        p_stmt = p_stmt.where(Purchase.purchase_date <= date_to)
    if currency is not None:
        p_stmt = p_stmt.where(Purchase.currency == currency)

    purchases = list((await session.scalars(p_stmt)).all())
    if not purchases:
        if currency is not None:
            return [
                CurrencySpendingSummary(
                    currency=currency,
                    total_spending=Decimal("0.00"),
                    food_spending=Decimal("0.00"),
                    household_spending=Decimal("0.00"),
                    purchase_count=0,
                    average_purchase_value=Decimal("0.00"),
                )
            ]
        return []

    purchase_map = {p.id: p for p in purchases}
    items = list(
        (
            await session.scalars(
                select(PurchaseItem).where(PurchaseItem.purchase_id.in_(purchase_map.keys()))
            )
        ).all()
    )

    totals_by_curr: dict[str, Decimal] = {}
    counts_by_curr: dict[str, int] = {}
    food_by_curr: dict[str, Decimal] = {}
    hh_by_curr: dict[str, Decimal] = {}

    for p in purchases:
        totals_by_curr[p.currency] = totals_by_curr.get(p.currency, Decimal("0.00")) + p.amount
        counts_by_curr[p.currency] = counts_by_curr.get(p.currency, 0) + 1
        food_by_curr.setdefault(p.currency, Decimal("0.00"))
        hh_by_curr.setdefault(p.currency, Decimal("0.00"))

    for it in items:
        curr = purchase_map[it.purchase_id].currency
        macro = _resolve_item_macro(it, macro_lookup)
        if macro == "food":
            food_by_curr[curr] += it.effective_total_price
        else:
            hh_by_curr[curr] += it.effective_total_price

    results: list[CurrencySpendingSummary] = []
    for curr in sorted(totals_by_curr.keys()):
        total = quantize_money(totals_by_curr[curr])
        cnt = counts_by_curr[curr]
        avg = quantize_money(total / Decimal(cnt)) if cnt > 0 else Decimal("0.00")
        results.append(
            CurrencySpendingSummary(
                currency=cast(SupportedCurrency, curr),
                total_spending=total,
                food_spending=quantize_money(food_by_curr[curr]),
                household_spending=quantize_money(hh_by_curr[curr]),
                purchase_count=cnt,
                average_purchase_value=avg,
            )
        )
    return results


async def get_category_analytics(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    macro_filter: MacroGroup | None = None,
) -> list[CategorySpendingRow]:
    macro_lookup = await _load_macro_lookup(session)
    stmt = (
        select(PurchaseItem, Purchase)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .where(Purchase.user_id == user_id, Purchase.currency == currency)
    )
    if date_from is not None:
        stmt = stmt.where(Purchase.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Purchase.purchase_date <= date_to)

    rows = (await session.execute(stmt)).all()
    grouped: dict[tuple[uuid.UUID | None, str, MacroGroup], tuple[Decimal, int]] = {}

    for item, _purchase in rows:
        macro = _resolve_item_macro(item, macro_lookup)
        if macro_filter is not None and macro != macro_filter:
            continue
        key = (
            item.category_id_snapshot,
            item.category_name_snapshot or "Uncategorized",
            macro,
        )
        prev_sum, prev_cnt = grouped.get(key, (Decimal("0.00"), 0))
        grouped[key] = (prev_sum + item.effective_total_price, prev_cnt + 1)

    grand_total = sum((v[0] for v in grouped.values()), Decimal("0.00"))
    result: list[CategorySpendingRow] = []
    for (cat_id, cat_name, macro), (amt, cnt) in grouped.items():
        share = (
            ((amt / grand_total) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if grand_total > Decimal("0")
            else Decimal("0.00")
        )
        result.append(
            CategorySpendingRow(
                category_id=cat_id,
                category_name=cat_name,
                macro_group=macro,
                currency=currency,
                total_spending=quantize_money(amt),
                item_count=cnt,
                share_pct=share,
            )
        )
    result.sort(key=lambda r: r.total_spending, reverse=True)
    return result


async def get_household_spending(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> HouseholdSpendingResponse:
    cats = await get_category_analytics(
        session,
        user_id,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
        macro_filter="household",
    )
    total_hh = quantize_money(sum((c.total_spending for c in cats), Decimal("0.00")))
    return HouseholdSpendingResponse(
        currency=currency,
        total_household_spending=total_hh,
        categories=cats,
    )


async def get_store_analytics(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[StoreSpendingRow]:
    stmt = (
        select(Purchase, Store, StoreChain)
        .outerjoin(Store, Store.id == Purchase.store_id)
        .outerjoin(StoreChain, StoreChain.id == Store.store_chain_id)
        .where(Purchase.user_id == user_id, Purchase.currency == currency)
    )
    if date_from is not None:
        stmt = stmt.where(Purchase.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Purchase.purchase_date <= date_to)

    rows = (await session.execute(stmt)).all()
    grouped: dict[uuid.UUID | None, list[tuple[Purchase, Store | None, StoreChain | None]]] = {}
    for p, s, c in rows:
        grouped.setdefault(p.store_id, []).append((p, s, c))

    out: list[StoreSpendingRow] = []
    for store_id, entries in grouped.items():
        _, st, ch = entries[0]
        total = quantize_money(sum((e[0].amount for e in entries), Decimal("0.00")))
        cnt = len(entries)
        out.append(
            StoreSpendingRow(
                store_id=store_id,
                store_display_name=st.display_name if st else "Unspecified Store",
                chain_slug=ch.slug if ch else None,
                currency=currency,
                total_spending=total,
                purchase_count=cnt,
                average_purchase_value=quantize_money(total / Decimal(cnt)),
            )
        )
    out.sort(key=lambda r: r.total_spending, reverse=True)
    return out


async def get_monthly_trends(
    session: AsyncSession,
    profile: Profile,
    *,
    currency: SupportedCurrency = "RON",
    months: int = 6,
    reference_date: date | None = None,
) -> list[MonthlyTrendPoint]:
    tz = ZoneInfo(profile.timezone)
    ref = reference_date or datetime.now(tz).date()

    # Generate chronological list of YYYY-MM buckets ending at ref month
    month_keys: list[str] = []
    y, m = ref.year, ref.month
    for _ in range(max(1, months)):
        month_keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_keys.reverse()

    macro_lookup = await _load_macro_lookup(session)
    purchases = list(
        (
            await session.scalars(
                select(Purchase).where(
                    Purchase.user_id == profile.id,
                    Purchase.currency == currency,
                )
            )
        ).all()
    )
    purchase_map = {p.id: p for p in purchases}
    items = (
        list(
            (
                await session.scalars(
                    select(PurchaseItem).where(PurchaseItem.purchase_id.in_(purchase_map.keys()))
                )
            ).all()
        )
        if purchase_map
        else []
    )

    bucket_totals = {mk: Decimal("0.00") for mk in month_keys}
    bucket_food = {mk: Decimal("0.00") for mk in month_keys}
    bucket_hh = {mk: Decimal("0.00") for mk in month_keys}
    bucket_counts = {mk: 0 for mk in month_keys}
    purchase_month: dict[uuid.UUID, str] = {}

    for p in purchases:
        local_dt = _ensure_utc(p.purchase_date).astimezone(tz)
        mk = f"{local_dt.year:04d}-{local_dt.month:02d}"
        purchase_month[p.id] = mk
        if mk in bucket_totals:
            bucket_totals[mk] += p.amount
            bucket_counts[mk] += 1

    for it in items:
        mk = purchase_month.get(it.purchase_id, "")
        if mk in bucket_totals:
            if _resolve_item_macro(it, macro_lookup) == "food":
                bucket_food[mk] += it.effective_total_price
            else:
                bucket_hh[mk] += it.effective_total_price

    return [
        MonthlyTrendPoint(
            month=mk,
            currency=currency,
            total_spending=quantize_money(bucket_totals[mk]),
            food_spending=quantize_money(bucket_food[mk]),
            household_spending=quantize_money(bucket_hh[mk]),
            purchase_count=bucket_counts[mk],
        )
        for mk in month_keys
    ]


async def get_top_products(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: Literal["spending", "frequency"] = "spending",
    limit: int = 10,
) -> list[TopProductRow]:
    stmt = (
        select(PurchaseItem, Purchase, Product)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .outerjoin(Product, Product.id == PurchaseItem.product_id)
        .where(Purchase.user_id == user_id, Purchase.currency == currency)
    )
    if date_from is not None:
        stmt = stmt.where(Purchase.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Purchase.purchase_date <= date_to)

    rows = (await session.execute(stmt)).all()
    grouped: dict[tuple[uuid.UUID | None, str], tuple[Decimal, Decimal, set[uuid.UUID]]] = {}

    for item, purchase, prod in rows:
        key = (
            prod.id if prod else None,
            prod.normalized_name if prod else item.raw_name,
        )
        prev_spend, prev_qty, prev_p_ids = grouped.get(
            key, (Decimal("0.00"), Decimal("0.000"), set())
        )
        grouped[key] = (
            prev_spend + item.effective_total_price,
            prev_qty + item.quantity,
            {*prev_p_ids, purchase.id},
        )

    out = [
        TopProductRow(
            product_id=pid,
            product_name=pname,
            currency=currency,
            total_spending=quantize_money(spend),
            total_quantity=qty,
            purchase_count=len(p_ids),
        )
        for (pid, pname), (spend, qty, p_ids) in grouped.items()
    ]
    if sort_by == "frequency":
        out.sort(key=lambda r: (r.purchase_count, r.total_spending), reverse=True)
    else:
        out.sort(key=lambda r: r.total_spending, reverse=True)
    return out[:limit]


async def get_price_changes(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
    limit: int = 10,
) -> list[PriceChangeRow]:
    """Detect regular price changes for products with >=2 comparable observations."""
    stmt = (
        select(PurchaseItem, Purchase, Product)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .join(Product, Product.id == PurchaseItem.product_id)
        .where(
            Purchase.user_id == user_id,
            Purchase.currency == currency,
            PurchaseItem.regular_standard_unit_price.is_not(None),
        )
        .order_by(Purchase.purchase_date.asc(), PurchaseItem.created_at.asc())
    )
    rows = (await session.execute(stmt)).all()

    by_prod: dict[uuid.UUID, list[tuple[PurchaseItem, Purchase, Product]]] = {}
    for item, purchase, prod in rows:
        if item.standard_unit_snapshot == prod.standard_unit:
            by_prod.setdefault(prod.id, []).append((item, purchase, prod))

    changes: list[PriceChangeRow] = []
    for prod_id, obs in by_prod.items():
        if len(obs) < 2:
            continue
        prev_item, prev_purchase, prod = obs[-2]
        last_item, last_purchase, _ = obs[-1]
        prev_p = prev_item.regular_standard_unit_price or Decimal("0")
        last_p = last_item.regular_standard_unit_price or Decimal("0")
        if prev_p <= Decimal("0") or prev_p == last_p:
            continue
        diff = last_p - prev_p
        pct = ((diff / prev_p) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        changes.append(
            PriceChangeRow(
                product_id=prod_id,
                product_name=prod.normalized_name,
                currency=currency,
                standard_unit=prod.standard_unit,
                previous_regular_price=prev_p,
                latest_regular_price=last_p,
                abs_change=diff,
                pct_change=pct,
                previous_observed_at=prev_purchase.purchase_date,
                latest_observed_at=last_purchase.purchase_date,
                observation_count=len(obs),
            )
        )

    changes.sort(key=lambda c: abs(c.pct_change), reverse=True)
    return changes[:limit]

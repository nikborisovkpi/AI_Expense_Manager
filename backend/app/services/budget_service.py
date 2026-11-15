"""Timezone-aware shopping budget CRUD and utilization calculation service."""

from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SupportedCurrency
from app.core.errors import ValidationDomainError
from app.models.budget import Budget
from app.models.category import Category
from app.models.profile import Profile, default_profile_preferences
from app.models.purchase import Purchase, PurchaseItem
from app.models.store import Store
from app.repositories.base import BaseRepository
from app.schemas.budget import (
    BudgetCreateRequest,
    BudgetPeriod,
    BudgetStatusResponse,
    BudgetUpdateRequest,
)
from app.services.catalog_service import get_visible_category_or_raise
from app.services.pricing_service import quantize_money


def resolve_month_bounds_utc(
    year: int,
    month: int,
    tz_name: str,
) -> tuple[datetime, datetime, date, date]:
    """Return [start_utc, end_excl_utc, start_local, end_local] in user's timezone."""
    tz = ZoneInfo(tz_name)
    last_day = calendar.monthrange(year, month)[1]
    start_date_local = date(year, month, 1)
    end_date_local = date(year, month, last_day)

    start_local_dt = datetime.combine(start_date_local, time.min, tzinfo=tz)
    next_day = end_date_local + timedelta(days=1)
    end_exclusive_local_dt = datetime.combine(next_day, time.min, tzinfo=tz)

    return (
        start_local_dt.astimezone(UTC),
        end_exclusive_local_dt.astimezone(UTC),
        start_date_local,
        end_date_local,
    )


def resolve_date_bounds_utc(
    start_local: date,
    end_local: date,
    tz_name: str,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start_dt = datetime.combine(start_local, time.min, tzinfo=tz).astimezone(UTC)
    end_excl_dt = datetime.combine(end_local + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        UTC
    )
    return start_dt, end_excl_dt


async def list_budgets(session: AsyncSession, user_id: uuid.UUID) -> list[Budget]:
    repo = BaseRepository(session, user_id, Budget)
    stmt = repo.scoped_select().order_by(Budget.created_at.desc())
    return await repo.list_matching(stmt)


async def create_budget(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: BudgetCreateRequest,
) -> Budget:
    if payload.end_date is not None and payload.end_date < payload.start_date:
        raise ValidationDomainError("Budget end_date cannot precede start_date")

    repo = BaseRepository(session, user_id, Budget)
    if payload.category_id is not None:
        await get_visible_category_or_raise(session, user_id, payload.category_id)
    if payload.store_id is not None:
        await repo.verify_owned_reference(Store, payload.store_id)

    budget = await repo.create(
        name=payload.name.strip() if payload.name else None,
        category_id=payload.category_id,
        store_id=payload.store_id,
        amount=quantize_money(payload.amount),
        currency=payload.currency,
        period=payload.period,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    await session.commit()
    await session.refresh(budget)
    return budget


async def update_budget(
    session: AsyncSession,
    user_id: uuid.UUID,
    budget_id: uuid.UUID,
    payload: BudgetUpdateRequest,
) -> Budget:
    repo = BaseRepository(session, user_id, Budget)
    budget = await repo.get_by_id_or_raise(budget_id)

    if payload.category_id is not None:
        await get_visible_category_or_raise(session, user_id, payload.category_id)
        budget.category_id = payload.category_id
    if payload.store_id is not None:
        await repo.verify_owned_reference(Store, payload.store_id)
        budget.store_id = payload.store_id
    if payload.name is not None:
        budget.name = payload.name.strip() or None
    if payload.amount is not None:
        budget.amount = quantize_money(payload.amount)
    if payload.currency is not None:
        budget.currency = payload.currency
    if payload.period is not None:
        budget.period = payload.period
    if payload.start_date is not None:
        budget.start_date = payload.start_date
    if payload.end_date is not None:
        budget.end_date = payload.end_date

    if budget.end_date is not None and budget.end_date < budget.start_date:
        raise ValidationDomainError("Budget end_date cannot precede start_date")

    await session.commit()
    await session.refresh(budget)
    return budget


async def delete_budget(session: AsyncSession, user_id: uuid.UUID, budget_id: uuid.UUID) -> None:
    repo = BaseRepository(session, user_id, Budget)
    await repo.delete(budget_id)
    await session.commit()


async def get_budgets_status(
    session: AsyncSession,
    profile: Profile,
    *,
    reference_date: date | None = None,
) -> list[BudgetStatusResponse]:
    tz_name = profile.timezone
    tz = ZoneInfo(tz_name)
    ref_local = reference_date or datetime.now(tz).date()

    prefs = {**default_profile_preferences(), **(profile.preferences or {})}
    alert_threshold = int(prefs.get("budget_alert_threshold_pct", 80))
    alerts_enabled = bool(prefs.get("budget_alerts_enabled", True))

    budgets = await list_budgets(session, profile.id)
    if not budgets:
        return []

    categories_map = {c.id: c.name for c in (await session.scalars(select(Category))).all()}
    stores_map = {
        s.id: s.display_name
        for s in (await session.scalars(select(Store).where(Store.user_id == profile.id))).all()
    }

    statuses: list[BudgetStatusResponse] = []
    for b in budgets:
        if b.period == "monthly":
            start_utc, end_excl_utc, win_start, win_end = resolve_month_bounds_utc(
                ref_local.year, ref_local.month, tz_name
            )
        else:
            win_start = b.start_date
            win_end = b.end_date or ref_local
            start_utc, end_excl_utc = resolve_date_bounds_utc(win_start, win_end, tz_name)

        if b.category_id is not None:
            stmt = (
                select(PurchaseItem.effective_total_price)
                .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
                .where(
                    Purchase.user_id == profile.id,
                    Purchase.currency == b.currency,
                    Purchase.purchase_date >= start_utc,
                    Purchase.purchase_date < end_excl_utc,
                    (PurchaseItem.category_id_snapshot == b.category_id)
                    | (PurchaseItem.parent_category_id_snapshot == b.category_id),
                )
            )
            if b.store_id is not None:
                stmt = stmt.where(Purchase.store_id == b.store_id)
            item_vals = list((await session.scalars(stmt)).all())
            spent = quantize_money(sum(item_vals, Decimal("0.00")))
        else:
            p_stmt = select(Purchase.amount).where(
                Purchase.user_id == profile.id,
                Purchase.currency == b.currency,
                Purchase.purchase_date >= start_utc,
                Purchase.purchase_date < end_excl_utc,
            )
            if b.store_id is not None:
                p_stmt = p_stmt.where(Purchase.store_id == b.store_id)
            p_vals = list((await session.scalars(p_stmt)).all())
            spent = quantize_money(sum(p_vals, Decimal("0.00")))

        remaining = quantize_money(b.amount - spent)
        utilization = (
            ((spent / b.amount) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if b.amount > Decimal("0")
            else Decimal("0.00")
        )
        is_exceeded = spent > b.amount
        is_alert = alerts_enabled and utilization >= Decimal(alert_threshold)

        statuses.append(
            BudgetStatusResponse(
                budget_id=b.id,
                name=b.name,
                category_id=b.category_id,
                category_name=categories_map.get(b.category_id) if b.category_id else None,
                store_id=b.store_id,
                store_display_name=stores_map.get(b.store_id) if b.store_id else None,
                currency=cast(SupportedCurrency, b.currency),
                period=cast(BudgetPeriod, b.period),
                window_start_local=win_start,
                window_end_local=win_end,
                timezone=tz_name,
                limit_amount=b.amount,
                spent=spent,
                remaining=remaining,
                utilization_pct=utilization,
                alert_threshold_pct=alert_threshold,
                is_alert=is_alert,
                is_exceeded=is_exceeded,
            )
        )

    return statuses

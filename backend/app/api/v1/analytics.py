"""API routes for Analytics and cached Dashboard Insights."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile, get_current_user_id
from app.core.config import SupportedCurrency
from app.db.session import get_db_session
from app.models.profile import Profile
from app.schemas.analytics import (
    CategorySpendingRow,
    CurrencySpendingSummary,
    DashboardInsightResponse,
    HouseholdSpendingResponse,
    MonthlyTrendPoint,
    PriceChangeRow,
    StoreSpendingRow,
    TopProductRow,
)
from app.services.analytics_service import (
    get_category_analytics,
    get_household_spending,
    get_monthly_trends,
    get_price_changes,
    get_spending_summary,
    get_store_analytics,
    get_top_products,
)
from app.services.insight_service import get_cached_dashboard_insight

router = APIRouter()


@router.get(
    "/analytics/summary",
    response_model=list[CurrencySpendingSummary],
    tags=["analytics"],
)
async def read_analytics_summary(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    currency: SupportedCurrency | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[CurrencySpendingSummary]:
    return await get_spending_summary(
        session,
        user_id,
        date_from=date_from,
        date_to=date_to,
        currency=currency,
    )


@router.get(
    "/analytics/categories",
    response_model=list[CategorySpendingRow],
    tags=["analytics"],
)
async def read_analytics_categories(
    currency: SupportedCurrency = Query(default="RON"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[CategorySpendingRow]:
    return await get_category_analytics(
        session,
        user_id,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/analytics/household-spending",
    response_model=HouseholdSpendingResponse,
    tags=["analytics"],
)
async def read_household_spending(
    currency: SupportedCurrency = Query(default="RON"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> HouseholdSpendingResponse:
    return await get_household_spending(
        session,
        user_id,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/analytics/stores",
    response_model=list[StoreSpendingRow],
    tags=["analytics"],
)
async def read_analytics_stores(
    currency: SupportedCurrency = Query(default="RON"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[StoreSpendingRow]:
    return await get_store_analytics(
        session,
        user_id,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/analytics/trends",
    response_model=list[MonthlyTrendPoint],
    tags=["analytics"],
)
async def read_analytics_trends(
    currency: SupportedCurrency = Query(default="RON"),
    months: int = Query(default=6, ge=1, le=24),
    reference_date: date | None = None,
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
) -> list[MonthlyTrendPoint]:
    return await get_monthly_trends(
        session,
        profile,
        currency=currency,
        months=months,
        reference_date=reference_date,
    )


@router.get(
    "/analytics/top-products",
    response_model=list[TopProductRow],
    tags=["analytics"],
)
async def read_top_products(
    currency: SupportedCurrency = Query(default="RON"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: Literal["spending", "frequency"] = Query(default="spending"),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[TopProductRow]:
    return await get_top_products(
        session,
        user_id,
        currency=currency,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        limit=limit,
    )


@router.get(
    "/analytics/price-changes",
    response_model=list[PriceChangeRow],
    tags=["analytics"],
)
async def read_price_changes(
    currency: SupportedCurrency = Query(default="RON"),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[PriceChangeRow]:
    return await get_price_changes(session, user_id, currency=currency, limit=limit)


@router.get(
    "/dashboard/insights",
    response_model=DashboardInsightResponse,
    tags=["analytics"],
)
async def read_dashboard_insights(
    currency: SupportedCurrency = Query(default="RON"),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> DashboardInsightResponse:
    return await get_cached_dashboard_insight(session, user_id, currency=currency)

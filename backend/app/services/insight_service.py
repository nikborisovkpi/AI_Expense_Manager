"""Cached dashboard insights reader and background refresher (never invokes LLM on GET)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import SupportedCurrency
from app.db.base import utcnow
from app.models.insight import DashboardInsight
from app.models.profile import Profile
from app.models.purchase import Purchase
from app.schemas.analytics import DashboardInsightResponse
from app.services.analytics_service import (
    get_price_changes,
    get_spending_summary,
    get_top_products,
)


async def get_cached_dashboard_insight(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
) -> DashboardInsightResponse:
    """Strictly read-only lookup from dashboard_insights cache (0 LLM calls)."""
    insight = await session.scalar(
        select(DashboardInsight).where(
            DashboardInsight.user_id == user_id,
            DashboardInsight.insight_type == "overview",
            DashboardInsight.currency == currency,
        )
    )
    if insight is None:
        return DashboardInsightResponse(
            id=None,
            insight_type="overview",
            currency=currency,
            status="stale",
            is_refreshing=False,
            data_version=0,
            generated_at=None,
            last_purchase_at=None,
            source_purchase_ids=[],
            content={
                "highlights": [
                    "Confirm your first supermarket purchase to unlock personalized insights."
                ]
            },
        )

    return DashboardInsightResponse(
        id=insight.id,
        insight_type=insight.insight_type,
        currency=cast(SupportedCurrency, insight.currency),
        status=insight.status,
        is_refreshing=insight.is_refreshing,
        data_version=insight.data_version,
        generated_at=insight.generated_at,
        last_purchase_at=insight.last_purchase_at,
        source_purchase_ids=[str(pid) for pid in (insight.source_purchase_ids or [])],
        content=insight.content or {},
    )


async def refresh_stale_dashboard_insights(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Refresh stale dashboard_insights rows deterministically from confirmed purchase metrics."""
    async with session_factory() as session:
        stale_rows = list(
            (
                await session.scalars(
                    select(DashboardInsight).where(DashboardInsight.status == "stale")
                )
            ).all()
        )
        refreshed = 0
        for row in stale_rows:
            profile = await session.scalar(select(Profile).where(Profile.id == row.user_id))
            if profile is None:
                continue

            curr = cast(SupportedCurrency, row.currency)
            summaries = await get_spending_summary(session, profile.id, currency=curr)
            summary = summaries[0]
            top_prods = await get_top_products(session, profile.id, currency=curr, limit=3)
            price_moves = await get_price_changes(session, profile.id, currency=curr, limit=3)

            recent_purchase_ids = [
                str(pid)
                for pid in (
                    await session.scalars(
                        select(Purchase.id)
                        .where(Purchase.user_id == profile.id, Purchase.currency == curr)
                        .order_by(Purchase.purchase_date.desc())
                        .limit(20)
                    )
                ).all()
            ]

            highlights: list[str] = []
            if summary.purchase_count > 0:
                highlights.append(
                    f"Total confirmed spending: {summary.total_spending} {curr} across "
                    f"{summary.purchase_count} trips (Food: {summary.food_spending} {curr}, "
                    f"Household: {summary.household_spending} {curr})."
                )
            if top_prods:
                leader = top_prods[0]
                highlights.append(
                    f"Top product: {leader.product_name} ({leader.total_spending} {curr})."
                )
            for pm in price_moves:
                direction = "increased" if pm.pct_change > 0 else "decreased"
                highlights.append(
                    f"Regular price for {pm.product_name} {direction} by {abs(pm.pct_change)}% "
                    f"({pm.previous_regular_price} -> "
                    f"{pm.latest_regular_price} {curr}/{pm.standard_unit})."
                )

            now = utcnow()
            row.content = {
                "highlights": highlights,
                "summary": summary.model_dump(mode="json"),
            }
            row.source_purchase_ids = recent_purchase_ids
            row.generated_at = now
            row.expires_at = now + timedelta(days=7)
            row.is_refreshing = False
            row.status = "ready"
            refreshed += 1

        await session.commit()
        return refreshed

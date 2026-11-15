"""10 typed read-only analytical tools for the AI Shopping Assistant (Section 8.2)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.date_resolver import resolve_relative_period
from app.core.config import ALLOWED_CURRENCIES, SupportedCurrency
from app.db.base import utcnow
from app.models.profile import Profile
from app.models.purchase import Purchase
from app.services.analytics_service import (
    get_category_analytics,
    get_price_changes,
    get_spending_summary,
    get_top_products,
)
from app.services.budget_service import get_budgets_status
from app.services.catalog_service import (
    compare_product_store_prices,
    get_product_price_history,
    list_user_products,
)
from app.services.purchase_service import list_purchases
from app.services.shopping_list_service import list_shopping_lists


def sanitize_untrusted_text(value: str | None, *, max_len: int = 120) -> str | None:
    """Strip control characters and bound untrusted receipt/product strings before agent context."""
    if value is None:
        return None
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return cleaned[:max_len]


class PeriodMetadata(BaseModel):
    label: str
    start_date: str | None
    end_date: str | None
    timezone: str


class DataSufficiencyMetadata(BaseModel):
    is_sufficient: bool
    reason: str | None = None


class AnalyticalToolEnvelope(BaseModel):
    tool_name: str
    values: dict[str, Any]
    period: PeriodMetadata
    currency: SupportedCurrency
    observation_count: int
    last_observation_date: str | None
    source_record_ids: list[str]
    data_sufficiency: DataSufficiencyMetadata


@dataclass(frozen=True)
class AgentToolContext:
    session: AsyncSession
    profile: Profile
    now_utc: datetime | None = None


def _resolve_currency(raw: Any, profile: Profile) -> SupportedCurrency:
    if isinstance(raw, str) and raw.upper() in ALLOWED_CURRENCIES:
        return cast(SupportedCurrency, raw.upper())
    return cast(SupportedCurrency, profile.preferred_currency)


READ_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_purchases",
            "description": "Retrieve confirmed shopping purchases for a period and currency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "this_month, last_month, last_3_months, last_30_days",
                    },
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spending_summary",
            "description": "Retrieve deterministic total, food, and household shopping expenses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_spending",
            "description": "Retrieve spending grouped by product category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budget_status",
            "description": "Retrieve current shopping budget utilization and alerts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_price_history",
            "description": (
                "Retrieve historical observed regular and paid prices for a specific product UUID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_store_prices",
            "description": (
                "Compare original regular prices per kg/l/piece across store chains "
                "for a product UUID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_products",
            "description": "Retrieve top purchased products by spending or purchase frequency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                    "sort_by": {"type": "string", "enum": ["spending", "frequency"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_changes",
            "description": "Identify products with notable observed regular price changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "currency": {"type": "string", "enum": ["RON", "UAH", "EUR", "USD"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search user products by name or brand to resolve IDs and detect ambiguity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shopping_lists",
            "description": "Retrieve existing shopping lists and estimated totals.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


async def execute_read_tool(
    ctx: AgentToolContext,
    tool_name: str,
    args: dict[str, Any],
) -> AnalyticalToolEnvelope:
    now = ctx.now_utc or utcnow()
    curr = _resolve_currency(args.get("currency"), ctx.profile)
    win = resolve_relative_period(
        args.get("period"),
        now,
        ctx.profile.timezone,
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    period_meta = PeriodMetadata(
        label=win.label,
        start_date=win.start_local.isoformat(),
        end_date=win.end_local.isoformat(),
        timezone=win.timezone,
    )

    if tool_name == "get_purchases":
        purchases = await list_purchases(
            ctx.session,
            ctx.profile.id,
            date_from=win.start_utc,
            date_to=win.end_exclusive_utc,
            currency=curr,
        )
        items_out = [
            {
                "id": str(p.id),
                "title": sanitize_untrusted_text(p.title),
                "store": sanitize_untrusted_text(p.store_display_name),
                "amount": str(p.amount),
                "currency": p.currency,
                "purchase_date": p.purchase_date.isoformat(),
            }
            for p in purchases[:25]
        ]
        last_dt = purchases[0].purchase_date.isoformat() if purchases else None
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={"purchases": items_out},
            period=period_meta,
            currency=curr,
            observation_count=len(purchases),
            last_observation_date=last_dt,
            source_record_ids=[str(p.id) for p in purchases[:25]],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(purchases) > 0,
                reason=None if purchases else f"No confirmed purchases in {curr} for {win.label}.",
            ),
        )

    if tool_name == "get_spending_summary":
        summaries = await get_spending_summary(
            ctx.session,
            ctx.profile.id,
            date_from=win.start_utc,
            date_to=win.end_exclusive_utc,
            currency=curr,
        )
        summary = summaries[0]
        p_rows = list(
            (
                await ctx.session.scalars(
                    select(Purchase)
                    .where(
                        Purchase.user_id == ctx.profile.id,
                        Purchase.currency == curr,
                        Purchase.purchase_date >= win.start_utc,
                        Purchase.purchase_date < win.end_exclusive_utc,
                    )
                    .order_by(Purchase.purchase_date.desc())
                    .limit(25)
                )
            ).all()
        )
        last_dt = p_rows[0].purchase_date.isoformat() if p_rows else None
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values=summary.model_dump(mode="json"),
            period=period_meta,
            currency=curr,
            observation_count=summary.purchase_count,
            last_observation_date=last_dt,
            source_record_ids=[str(p.id) for p in p_rows],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=summary.purchase_count > 0,
                reason=None
                if summary.purchase_count > 0
                else f"No confirmed purchases in {curr} during {win.label}.",
            ),
        )

    if tool_name == "get_category_spending":
        cats = await get_category_analytics(
            ctx.session,
            ctx.profile.id,
            currency=curr,
            date_from=win.start_utc,
            date_to=win.end_exclusive_utc,
        )
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={"categories": [c.model_dump(mode="json") for c in cats]},
            period=period_meta,
            currency=curr,
            observation_count=sum(c.item_count for c in cats),
            last_observation_date=None,
            source_record_ids=[str(c.category_id) for c in cats if c.category_id],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(cats) > 0,
                reason=None if cats else f"No categorized spending in {curr} during {win.label}.",
            ),
        )

    if tool_name == "get_budget_status":
        statuses = await get_budgets_status(ctx.session, ctx.profile)
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={"budgets": [s.model_dump(mode="json") for s in statuses]},
            period=period_meta,
            currency=curr,
            observation_count=len(statuses),
            last_observation_date=None,
            source_record_ids=[str(s.budget_id) for s in statuses],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(statuses) > 0,
                reason=None if statuses else "No shopping budgets have been configured yet.",
            ),
        )

    if tool_name == "get_product_price_history":
        prod_id = uuid.UUID(str(args["product_id"]))
        hist = await get_product_price_history(ctx.session, ctx.profile.id, prod_id, currency=curr)
        last_dt = hist.observations[-1].purchase_date.isoformat() if hist.observations else None
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values=hist.model_dump(mode="json"),
            period=PeriodMetadata(
                label="all_time",
                start_date=None,
                end_date=None,
                timezone=ctx.profile.timezone,
            ),
            currency=curr,
            observation_count=hist.observation_count,
            last_observation_date=last_dt,
            source_record_ids=[str(o.purchase_id) for o in hist.observations[-20:]],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=hist.observation_count > 0,
                reason=None
                if hist.observation_count > 0
                else f"No confirmed price observations for {hist.product_name} in {curr}.",
            ),
        )

    if tool_name == "compare_store_prices":
        prod_id = uuid.UUID(str(args["product_id"]))
        comp = await compare_product_store_prices(
            ctx.session, ctx.profile.id, prod_id, currency=curr
        )
        last_dt = (
            max(s.latest_observed_at for s in comp.stores).isoformat() if comp.stores else None
        )
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values=comp.model_dump(mode="json"),
            period=PeriodMetadata(
                label="all_time",
                start_date=None,
                end_date=None,
                timezone=ctx.profile.timezone,
            ),
            currency=curr,
            observation_count=sum(s.observation_count for s in comp.stores),
            last_observation_date=last_dt,
            source_record_ids=[s.group_key for s in comp.stores],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=comp.is_sufficient,
                reason=comp.insufficiency_reason,
            ),
        )

    if tool_name == "get_top_products":
        sort_by: Literal["spending", "frequency"] = (
            "frequency" if args.get("sort_by") == "frequency" else "spending"
        )
        top = await get_top_products(
            ctx.session,
            ctx.profile.id,
            currency=curr,
            date_from=win.start_utc,
            date_to=win.end_exclusive_utc,
            sort_by=sort_by,
        )
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={"products": [t.model_dump(mode="json") for t in top]},
            period=period_meta,
            currency=curr,
            observation_count=len(top),
            last_observation_date=None,
            source_record_ids=[str(t.product_id) for t in top if t.product_id],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(top) > 0,
                reason=None if top else f"No purchased products in {curr} during {win.label}.",
            ),
        )

    if tool_name == "get_price_changes":
        changes = await get_price_changes(ctx.session, ctx.profile.id, currency=curr)
        last_dt = changes[0].latest_observed_at.isoformat() if changes else None
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={"price_changes": [c.model_dump(mode="json") for c in changes]},
            period=PeriodMetadata(
                label="all_time",
                start_date=None,
                end_date=None,
                timezone=ctx.profile.timezone,
            ),
            currency=curr,
            observation_count=len(changes),
            last_observation_date=last_dt,
            source_record_ids=[str(c.product_id) for c in changes],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(changes) > 0,
                reason=None
                if changes
                else (
                    "Not enough repeat product purchases (>=2 observations) "
                    "to detect price changes."
                ),
            ),
        )

    if tool_name == "search_products":
        query = str(args.get("query") or "").strip()
        prods = await list_user_products(ctx.session, ctx.profile.id, q=query)
        candidates = [
            {
                "id": str(p.id),
                "normalized_name": sanitize_untrusted_text(p.normalized_name),
                "brand": sanitize_untrusted_text(p.brand),
                "package_size": str(p.package_size),
                "package_unit": p.package_unit,
                "standard_unit": p.standard_unit,
            }
            for p in prods[:15]
        ]
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={
                "query": query,
                "ambiguous": len(candidates) > 1,
                "candidates": candidates,
            },
            period=PeriodMetadata(
                label="catalog",
                start_date=None,
                end_date=None,
                timezone=ctx.profile.timezone,
            ),
            currency=curr,
            observation_count=len(candidates),
            last_observation_date=None,
            source_record_ids=[c["id"] for c in candidates],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(candidates) > 0,
                reason=None if candidates else f"No catalog products matched '{query}'.",
            ),
        )

    if tool_name == "get_shopping_lists":
        lists = await list_shopping_lists(ctx.session, ctx.profile.id)
        return AnalyticalToolEnvelope(
            tool_name=tool_name,
            values={"shopping_lists": [sl.model_dump(mode="json") for sl in lists]},
            period=PeriodMetadata(
                label="active",
                start_date=None,
                end_date=None,
                timezone=ctx.profile.timezone,
            ),
            currency=curr,
            observation_count=len(lists),
            last_observation_date=None,
            source_record_ids=[str(sl.id) for sl in lists],
            data_sufficiency=DataSufficiencyMetadata(
                is_sufficient=len(lists) > 0,
                reason=None if lists else "No shopping lists found.",
            ),
        )

    raise ValueError(f"Unknown read tool: {tool_name!r}")

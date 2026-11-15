"""Pydantic schemas for shopping analytics and cached dashboard insights."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.core.config import SupportedCurrency
from app.schemas.catalog import MacroGroup


class CurrencySpendingSummary(BaseModel):
    currency: SupportedCurrency
    total_spending: Decimal
    food_spending: Decimal
    household_spending: Decimal
    purchase_count: int
    average_purchase_value: Decimal


class CategorySpendingRow(BaseModel):
    category_id: uuid.UUID | None
    category_name: str
    macro_group: MacroGroup
    currency: SupportedCurrency
    total_spending: Decimal
    item_count: int
    share_pct: Decimal


class HouseholdSpendingResponse(BaseModel):
    currency: SupportedCurrency
    total_household_spending: Decimal
    categories: list[CategorySpendingRow]


class StoreSpendingRow(BaseModel):
    store_id: uuid.UUID | None
    store_display_name: str
    chain_slug: str | None
    currency: SupportedCurrency
    total_spending: Decimal
    purchase_count: int
    average_purchase_value: Decimal


class MonthlyTrendPoint(BaseModel):
    month: str
    currency: SupportedCurrency
    total_spending: Decimal
    food_spending: Decimal
    household_spending: Decimal
    purchase_count: int


class TopProductRow(BaseModel):
    product_id: uuid.UUID | None
    product_name: str
    currency: SupportedCurrency
    total_spending: Decimal
    total_quantity: Decimal
    purchase_count: int


class PriceChangeRow(BaseModel):
    product_id: uuid.UUID
    product_name: str
    currency: SupportedCurrency
    standard_unit: str
    previous_regular_price: Decimal
    latest_regular_price: Decimal
    abs_change: Decimal
    pct_change: Decimal
    previous_observed_at: datetime
    latest_observed_at: datetime
    observation_count: int


class DashboardInsightResponse(BaseModel):
    id: uuid.UUID | None
    insight_type: str
    currency: SupportedCurrency
    status: str
    is_refreshing: bool
    data_version: int
    generated_at: datetime | None
    last_purchase_at: datetime | None
    source_purchase_ids: list[str]
    content: dict[str, Any]

"""Pydantic schemas for shopping budgets and budget utilization status."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import SupportedCurrency

BudgetPeriod = Literal["monthly", "custom"]


class BudgetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=Decimal("0"))
    currency: SupportedCurrency = "RON"
    period: BudgetPeriod = "monthly"
    start_date: date
    end_date: date | None = None


class BudgetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None
    amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    currency: SupportedCurrency | None = None
    period: BudgetPeriod | None = None
    start_date: date | None = None
    end_date: date | None = None


class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    category_id: uuid.UUID | None
    store_id: uuid.UUID | None
    amount: Decimal
    currency: SupportedCurrency
    period: BudgetPeriod
    start_date: date
    end_date: date | None
    created_at: datetime
    updated_at: datetime


class BudgetStatusResponse(BaseModel):
    budget_id: uuid.UUID
    name: str | None
    category_id: uuid.UUID | None
    category_name: str | None
    store_id: uuid.UUID | None
    store_display_name: str | None
    currency: SupportedCurrency
    period: BudgetPeriod
    window_start_local: date
    window_end_local: date
    timezone: str
    limit_amount: Decimal
    spent: Decimal
    remaining: Decimal
    utilization_pct: Decimal
    alert_threshold_pct: int
    is_alert: bool
    is_exceeded: bool

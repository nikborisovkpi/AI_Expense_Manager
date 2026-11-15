"""Pydantic schemas for Shopping Lists and Shopping List Items."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import SupportedCurrency
from app.schemas.catalog import PackageUnit

ShoppingListStatus = Literal["active", "completed", "archived"]


class ShoppingListCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    store_id: uuid.UUID | None = None
    currency: SupportedCurrency = "RON"


class ShoppingListUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    store_id: uuid.UUID | None = None
    currency: SupportedCurrency | None = None
    status: ShoppingListStatus | None = None


class ShoppingListItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    product_name: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(default=Decimal("1.000"), gt=Decimal("0"))
    unit: PackageUnit = "piece"
    estimated_price: Decimal | None = Field(default=None, ge=Decimal("0"))


class ShoppingListItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    product_name: str | None = Field(default=None, min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, gt=Decimal("0"))
    unit: PackageUnit | None = None
    estimated_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    is_purchased: bool | None = None


class ShoppingListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shopping_list_id: uuid.UUID
    product_id: uuid.UUID | None
    product_name: str
    quantity: Decimal
    unit: str
    estimated_price: Decimal | None
    estimated_line_total: Decimal | None = None
    is_estimated: bool = True
    is_purchased: bool
    created_at: datetime
    updated_at: datetime


class ShoppingListResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID | None
    store_display_name: str | None
    name: str
    currency: SupportedCurrency
    status: ShoppingListStatus
    is_estimated: bool = True
    estimated_total: Decimal
    items_without_estimate_count: int
    items: list[ShoppingListItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

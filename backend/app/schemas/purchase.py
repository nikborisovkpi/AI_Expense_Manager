"""Pydantic schemas for confirmed purchases and purchase items."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import SupportedCurrency
from app.schemas.catalog import PackageUnit

PurchaseSource = Literal["manual", "receipt"]


class PurchaseItemCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    raw_name: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=Decimal("0"))
    unit: PackageUnit = "piece"
    unit_price: Decimal = Field(ge=Decimal("0"))
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    total_price: Decimal | None = Field(default=None, ge=Decimal("0"))


class PurchaseItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    raw_name: str | None = Field(default=None, min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, gt=Decimal("0"))
    unit: PackageUnit | None = None
    unit_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    discount_amount: Decimal | None = Field(default=None, ge=Decimal("0"))


class PurchaseItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_id: uuid.UUID
    product_id: uuid.UUID | None
    raw_name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    discount_amount: Decimal
    total_price: Decimal
    effective_total_price: Decimal
    category_id_snapshot: uuid.UUID | None
    parent_category_id_snapshot: uuid.UUID | None
    category_name_snapshot: str | None
    standard_unit_snapshot: str | None
    standard_quantity_snapshot: Decimal | None
    regular_standard_unit_price: Decimal | None
    paid_standard_unit_price: Decimal | None
    created_at: datetime


class PurchaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    subtotal: Decimal = Field(ge=Decimal("0"))
    discounts_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    tax_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    tax_included: bool = True
    container_deposit_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    rounding_adjustment: Decimal = Field(default=Decimal("0.00"))
    amount: Decimal = Field(ge=Decimal("0"))
    currency: SupportedCurrency = "RON"
    purchase_date: datetime
    description: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, max_length=128)
    items: list[PurchaseItemCreateInput] = Field(default_factory=list)


class PurchaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subtotal: Decimal | None = Field(default=None, ge=Decimal("0"))
    discounts_total: Decimal | None = Field(default=None, ge=Decimal("0"))
    tax_total: Decimal | None = Field(default=None, ge=Decimal("0"))
    tax_included: bool | None = None
    container_deposit_total: Decimal | None = Field(default=None, ge=Decimal("0"))
    rounding_adjustment: Decimal | None = None
    amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    currency: SupportedCurrency | None = None
    purchase_date: datetime | None = None
    description: str | None = Field(default=None, max_length=2000)


class PurchaseResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID | None
    store_display_name: str | None = None
    title: str
    subtotal: Decimal
    discounts_total: Decimal
    tax_total: Decimal
    tax_included: bool
    container_deposit_total: Decimal
    rounding_adjustment: Decimal
    amount: Decimal
    currency: SupportedCurrency
    purchase_date: datetime
    description: str | None
    source: PurchaseSource
    item_count: int = 0
    receipt_id: uuid.UUID | None = None
    receipt_status: str | None = None
    items: list[PurchaseItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

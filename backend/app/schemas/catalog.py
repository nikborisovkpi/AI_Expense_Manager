"""Pydantic schemas for categories, stores, products, aliases, and price comparisons."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import SupportedCurrency

MacroGroup = Literal["food", "household"]
ProductType = Literal["consumable", "durable"]
PackageUnit = Literal["piece", "pack", "pair", "g", "kg", "ml", "l"]
AliasStatus = Literal["suggested", "user_confirmed", "rejected"]


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    is_system: bool
    macro_group: MacroGroup
    name: str
    slug: str
    description: str | None
    icon: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryTreeNode(CategoryResponse):
    children: list[CategoryResponse] = Field(default_factory=list)


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    macro_group: MacroGroup = "household"
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=64)


class CategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    macro_group: MacroGroup | None = None
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class StoreChainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    canonical_name: str
    country: str | None
    is_fallback: bool


class StoreResponse(BaseModel):
    id: uuid.UUID
    store_chain_id: uuid.UUID
    chain_slug: str
    chain_name: str
    display_name: str
    branch_name: str | None
    address: str | None
    city: str | None
    country: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StoreCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_chain_id: uuid.UUID | None = None
    display_name: str = Field(min_length=1, max_length=200)
    branch_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=8)


class StoreUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_chain_id: uuid.UUID | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    branch_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=8)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    normalized_name: str
    brand: str | None
    product_type: ProductType
    package_size: Decimal
    package_unit: PackageUnit
    standard_unit: str
    standard_quantity: Decimal
    barcode: str | None
    description: str | None
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID
    normalized_name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=120)
    product_type: ProductType = "consumable"
    package_size: Decimal = Field(default=Decimal("1.000"), gt=Decimal("0"))
    package_unit: PackageUnit = "piece"
    barcode: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)


class ProductUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID | None = None
    normalized_name: str | None = Field(default=None, min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=120)
    product_type: ProductType | None = None
    package_size: Decimal | None = Field(default=None, gt=Decimal("0"))
    package_unit: PackageUnit | None = None
    barcode: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)


class ProductAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_chain_id: uuid.UUID
    product_id: uuid.UUID
    raw_name: str
    normalized_raw_name: str
    confirmation_status: AliasStatus
    confirmed_by_user_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PriceObservationPoint(BaseModel):
    purchase_id: uuid.UUID
    purchase_item_id: uuid.UUID
    purchase_date: datetime
    currency: SupportedCurrency
    store_id: uuid.UUID | None
    store_display_name: str | None
    chain_slug: str | None
    chain_name: str | None
    regular_unit_price: Decimal
    paid_effective_total: Decimal
    quantity: Decimal
    standard_unit: str | None
    regular_standard_unit_price: Decimal | None
    paid_standard_unit_price: Decimal | None


class ProductPriceHistoryResponse(BaseModel):
    product_id: uuid.UUID
    product_name: str
    standard_unit: str
    currency: SupportedCurrency
    observation_count: int
    min_regular_standard_price: Decimal | None
    max_regular_standard_price: Decimal | None
    avg_regular_standard_price: Decimal | None
    latest_regular_standard_price: Decimal | None
    observations: list[PriceObservationPoint]


class StorePriceComparisonRow(BaseModel):
    group_key: str
    group_slug: str
    display_name: str
    observation_count: int
    latest_observed_at: datetime
    latest_regular_unit_price: Decimal
    latest_regular_standard_price: Decimal | None
    avg_regular_standard_price: Decimal | None
    min_regular_standard_price: Decimal | None
    max_regular_standard_price: Decimal | None


class ProductStoreComparisonResponse(BaseModel):
    product_id: uuid.UUID
    product_name: str
    currency: SupportedCurrency
    standard_unit: str
    group_by: Literal["chain", "branch"]
    is_sufficient: bool
    insufficiency_reason: str | None
    cheapest_regular_group: str | None
    stores: list[StorePriceComparisonRow]

"""Structured extraction, editable review draft, and validation warning schemas for receipts."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import SupportedCurrency
from app.schemas.catalog import PackageUnit


class ExtractedLineItem(BaseModel):
    raw_name: str = Field(max_length=255)
    normalized_name: str = Field(max_length=255)
    brand: str | None = Field(default=None, max_length=120)
    category_slug: str | None = Field(default=None, max_length=120)
    quantity: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))
    unit: PackageUnit = "piece"
    package_size: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))
    package_unit: PackageUnit = "piece"
    unit_price: Decimal = Field(ge=Decimal("0"))
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    total_price: Decimal = Field(ge=Decimal("0"))
    is_deposit_line: bool = False
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class ExtractedReceiptPayload(BaseModel):
    store_name: str | None = Field(default=None, max_length=200)
    branch_name: str | None = Field(default=None, max_length=200)
    store_cui: str | None = Field(default=None, max_length=64)
    receipt_number: str | None = Field(default=None, max_length=120)
    purchase_date: str | None = Field(default=None, max_length=64)
    currency: SupportedCurrency = "RON"
    subtotal: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    discounts_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    tax_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    tax_included: bool = True
    container_deposit_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    rounding_adjustment: Decimal = Field(default=Decimal("0.00"))
    total: Decimal = Field(ge=Decimal("0"))
    items: list[ExtractedLineItem] = Field(default_factory=list)


class ValidationWarning(BaseModel):
    field: str
    code: str
    severity: Literal["warning", "error"] = "warning"
    message: str


class EditableDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_name: str = Field(min_length=1, max_length=255)
    normalized_name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    category_slug: str | None = Field(default=None, max_length=120)
    matched_product_id: uuid.UUID | None = None
    alias_confidence: Literal["confirmed", "suggested", "new"] = "new"
    confirm_alias: bool = True
    quantity: Decimal = Field(gt=Decimal("0"))
    unit: PackageUnit = "piece"
    package_size: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))
    package_unit: PackageUnit = "piece"
    unit_price: Decimal = Field(ge=Decimal("0"))
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    total_price: Decimal = Field(ge=Decimal("0"))
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EditableReceiptDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: uuid.UUID | None = None
    store_chain_id: uuid.UUID | None = None
    store_chain_slug: str = "other"
    store_name: str = Field(default="Unknown Store", min_length=1, max_length=200)
    branch_name: str | None = Field(default=None, max_length=200)
    store_cui: str | None = Field(default=None, max_length=64)
    receipt_number: str | None = Field(default=None, max_length=120)
    purchase_date: str | None = None
    currency: SupportedCurrency = "RON"
    subtotal: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    discounts_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    tax_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    tax_included: bool = True
    container_deposit_total: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    rounding_adjustment: Decimal = Field(default=Decimal("0.00"))
    total: Decimal = Field(ge=Decimal("0"))
    items: list[EditableDraftItem] = Field(default_factory=list)

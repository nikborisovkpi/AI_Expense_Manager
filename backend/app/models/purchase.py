"""Confirmed shopping purchases and dual-priced purchase items."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (
        CheckConstraint("source IN ('manual', 'receipt')", name="purchase_source_allowed"),
        CheckConstraint(
            "currency IN ('RON', 'UAH', 'EUR', 'USD')",
            name="purchase_currency_allowed",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_purchases_user_idempotency"),
        Index("ix_purchases_user_purchase_date", "user_id", "purchase_date"),
        Index("ix_purchases_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stores.id", ondelete="RESTRICT"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discounts_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    tax_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    container_deposit_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    rounding_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class PurchaseItem(Base):
    """Line item with immutable classification/unit snapshots and dual pricing."""

    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="purchase_item_quantity_positive"),
        Index("ix_purchase_items_purchase_id", "purchase_id"),
        Index("ix_purchase_items_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
    )
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="piece")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Immutable snapshots at confirmation time
    category_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    parent_category_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    category_name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    standard_unit_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    standard_quantity_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )

    # Dual standardized prices:
    # 1) regular_standard_unit_price: original pre-discount price per kg/l/pc (Store Comparison)
    # 2) paid_standard_unit_price: net effective price per kg/l/pc after promos (Expenses)
    regular_standard_unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    paid_standard_unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

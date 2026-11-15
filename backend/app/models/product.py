"""User-owned canonical products and retailer-specific receipt aliases."""

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


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "product_type IN ('consumable', 'durable')",
            name="product_type_allowed",
        ),
        CheckConstraint(
            "package_unit IN ('piece', 'pack', 'pair', 'g', 'kg', 'ml', 'l')",
            name="package_unit_allowed",
        ),
        CheckConstraint(
            "standard_unit IN ('piece', 'pack', 'pair', 'kg', 'l')",
            name="standard_unit_allowed",
        ),
        CheckConstraint("package_size > 0", name="package_size_positive"),
        CheckConstraint("standard_quantity > 0", name="standard_quantity_positive"),
        Index("ix_products_user_category", "user_id", "category_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_type: Mapped[str] = mapped_column(String(24), nullable=False, default="consumable")
    package_size: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
        default=Decimal("1.000"),
    )
    package_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="piece")
    standard_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="piece")
    standard_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("1.000000"),
    )
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        CheckConstraint(
            "confirmation_status IN ('suggested', 'user_confirmed', 'rejected')",
            name="alias_confirmation_status_allowed",
        ),
        UniqueConstraint(
            "user_id",
            "store_chain_id",
            "normalized_raw_name",
            name="uq_product_aliases_user_chain_raw",
        ),
        Index(
            "ix_product_aliases_lookup",
            "user_id",
            "store_chain_id",
            "normalized_raw_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_chain_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("store_chains.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="suggested",
    )
    confirmed_by_user_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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

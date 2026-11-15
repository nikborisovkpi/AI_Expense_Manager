"""Cached dashboard AI insights model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONVariant, utcnow


class DashboardInsight(Base):
    __tablename__ = "dashboard_insights"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'stale', 'failed')",
            name="insight_status_allowed",
        ),
        UniqueConstraint(
            "user_id",
            "insight_type",
            "currency",
            name="uq_dashboard_insights_user_type_currency",
        ),
        Index("ix_dashboard_insights_user_currency", "user_id", "currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    insight_type: Mapped[str] = mapped_column(String(64), nullable=False, default="overview")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    content: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    source_purchase_ids: Mapped[list[Any]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_refreshing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_purchase_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="stale")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

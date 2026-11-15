"""Local pseudo-account profile and singleton installation state models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONVariant, utcnow


def default_profile_preferences() -> dict[str, Any]:
    return {
        "budget_alert_threshold_pct": 80,
        "budget_alerts_enabled": True,
        "auto_refresh_insights": True,
    }


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "preferred_currency IN ('RON', 'UAH', 'EUR', 'USD')",
            name="preferred_currency_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Local Shopper")
    avatar_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avatar_mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant,
        nullable=False,
        default=default_profile_preferences,
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


class AppInstallation(Base):
    """Singleton pointer to the active local pseudo-account profile."""

    __tablename__ = "app_installation"
    __table_args__ = (CheckConstraint("singleton_key = true", name="singleton_only_true"),)

    singleton_key: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    active_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="RESTRICT"),
        nullable=False,
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

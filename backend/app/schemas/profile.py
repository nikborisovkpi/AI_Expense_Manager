"""Pydantic schemas for local profile and preferences."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import SupportedCurrency
from app.core.timezone import validate_timezone


class ProfilePreferencesSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_alert_threshold_pct: int = Field(default=80, ge=1, le=100)
    budget_alerts_enabled: bool = True
    auto_refresh_insights: bool = True


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    preferred_currency: SupportedCurrency
    locale: str
    timezone: str
    has_avatar: bool
    preferences: ProfilePreferencesSchema
    created_at: datetime
    updated_at: datetime


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    preferred_currency: SupportedCurrency | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    preferences: ProfilePreferencesSchema | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_timezone(value)

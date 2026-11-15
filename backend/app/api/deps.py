"""FastAPI dependencies resolving trusted server-side context."""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.models.profile import Profile
from app.services.profile_service import get_active_profile
from app.services.storage_service import PrivateStorageService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> PrivateStorageService:
    storage: PrivateStorageService = request.app.state.storage_service
    return storage


async def get_current_profile(
    session: AsyncSession = Depends(get_db_session),
) -> Profile:
    """Resolve the active installation profile exclusively from server-side DB state."""
    return await get_active_profile(session)


async def get_current_user_id(
    profile: Profile = Depends(get_current_profile),
) -> uuid.UUID:
    return profile.id

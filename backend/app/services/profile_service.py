"""Local pseudo-account bootstrap, profile management, and private avatar operations."""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, SupportedCurrency
from app.core.errors import BadRequestError, BootstrapUnavailableError, NotFoundError
from app.core.timezone import detect_local_timezone
from app.models.profile import AppInstallation, Profile, default_profile_preferences
from app.schemas.profile import ProfilePreferencesSchema, ProfileResponse, ProfileUpdateRequest
from app.services.storage_service import PrivateStorageService

ALLOWED_AVATAR_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB

_bootstrap_lock = asyncio.Lock()


def to_profile_response(profile: Profile) -> ProfileResponse:
    merged_prefs = {**default_profile_preferences(), **(profile.preferences or {})}
    return ProfileResponse(
        id=profile.id,
        display_name=profile.display_name,
        preferred_currency=cast(SupportedCurrency, profile.preferred_currency),
        locale=profile.locale,
        timezone=profile.timezone,
        has_avatar=bool(profile.avatar_path),
        preferences=ProfilePreferencesSchema(**merged_prefs),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def bootstrap_local_profile(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    default_currency: str = "RON",
    default_locale: str = "en",
) -> Profile:
    """Idempotently initialize or load the single installation profile."""
    async with _bootstrap_lock:
        async with session_factory() as session:
            installation = await session.scalar(
                select(AppInstallation).where(AppInstallation.singleton_key.is_(True))
            )
            if installation is not None:
                existing = await session.scalar(
                    select(Profile).where(Profile.id == installation.active_profile_id)
                )
                if existing is not None:
                    return existing

            try:
                profile = Profile(
                    display_name="Local Shopper",
                    preferred_currency=default_currency,
                    locale=default_locale,
                    timezone=detect_local_timezone(),
                    preferences=default_profile_preferences(),
                )
                session.add(profile)
                await session.flush()

                session.add(
                    AppInstallation(
                        singleton_key=True,
                        active_profile_id=profile.id,
                    )
                )
                await session.commit()
                await session.refresh(profile)
                return profile
            except IntegrityError:
                await session.rollback()
                installation = await session.scalar(
                    select(AppInstallation).where(AppInstallation.singleton_key.is_(True))
                )
                if installation is None:
                    raise BootstrapUnavailableError() from None
                existing = await session.scalar(
                    select(Profile).where(Profile.id == installation.active_profile_id)
                )
                if existing is None:
                    raise BootstrapUnavailableError() from None
                return existing


async def get_active_profile(session: AsyncSession) -> Profile:
    installation = await session.scalar(
        select(AppInstallation).where(AppInstallation.singleton_key.is_(True))
    )
    if installation is None:
        raise BootstrapUnavailableError()
    profile = await session.scalar(
        select(Profile).where(Profile.id == installation.active_profile_id)
    )
    if profile is None:
        raise BootstrapUnavailableError()
    return profile


async def update_active_profile(
    session: AsyncSession,
    profile: Profile,
    payload: ProfileUpdateRequest,
) -> Profile:
    if payload.display_name is not None:
        profile.display_name = payload.display_name.strip()
    if payload.preferred_currency is not None:
        profile.preferred_currency = payload.preferred_currency
    if payload.locale is not None:
        profile.locale = payload.locale.strip()
    if payload.timezone is not None:
        profile.timezone = payload.timezone
    if payload.preferences is not None:
        profile.preferences = payload.preferences.model_dump()

    await session.commit()
    await session.refresh(profile)
    return profile


async def upload_profile_avatar(
    *,
    session: AsyncSession,
    profile: Profile,
    storage: PrivateStorageService,
    settings: Settings,
    data: bytes,
    content_type: str,
) -> Profile:
    normalized_type = content_type.strip().lower()
    ext = ALLOWED_AVATAR_TYPES.get(normalized_type)
    if ext is None:
        raise BadRequestError(
            "Unsupported avatar image format. Allowed: JPEG, PNG, WEBP.",
            details={"content_type": content_type},
        )
    if not data or len(data) > MAX_AVATAR_BYTES:
        raise BadRequestError(
            "Avatar image must be non-empty and at most 5 MB.",
            details={"size_bytes": len(data)},
        )

    old_path = profile.avatar_path
    new_path = f"{profile.id}/{uuid.uuid4()}.{ext}"
    await storage.upload(
        bucket=settings.supabase_avatars_bucket,
        path=new_path,
        data=data,
        content_type=normalized_type,
    )
    if old_path and old_path != new_path:
        await storage.delete(bucket=settings.supabase_avatars_bucket, path=old_path)

    profile.avatar_path = new_path
    profile.avatar_mime_type = normalized_type
    await session.commit()
    await session.refresh(profile)
    return profile


async def download_profile_avatar(
    *,
    profile: Profile,
    storage: PrivateStorageService,
    settings: Settings,
) -> tuple[bytes, str]:
    if not profile.avatar_path:
        raise NotFoundError("Profile avatar not set")
    content, content_type = await storage.download(
        bucket=settings.supabase_avatars_bucket,
        path=profile.avatar_path,
    )
    return content, profile.avatar_mime_type or content_type


async def remove_profile_avatar(
    *,
    session: AsyncSession,
    profile: Profile,
    storage: PrivateStorageService,
    settings: Settings,
) -> Profile:
    if profile.avatar_path:
        await storage.delete(
            bucket=settings.supabase_avatars_bucket,
            path=profile.avatar_path,
        )
        profile.avatar_path = None
        profile.avatar_mime_type = None
        await session.commit()
        await session.refresh(profile)
    return profile

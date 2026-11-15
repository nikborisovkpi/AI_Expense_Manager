"""Local profile and private avatar endpoints (/api/v1/profile)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_current_profile, get_storage
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.profile import Profile
from app.schemas.profile import ProfileResponse, ProfileUpdateRequest
from app.services.profile_service import (
    download_profile_avatar,
    remove_profile_avatar,
    to_profile_response,
    update_active_profile,
    upload_profile_avatar,
)
from app.services.storage_service import PrivateStorageService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def read_profile(
    profile: Profile = Depends(get_current_profile),
) -> ProfileResponse:
    return to_profile_response(profile)


@router.patch("", response_model=ProfileResponse)
async def patch_profile(
    payload: ProfileUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
) -> ProfileResponse:
    updated = await update_active_profile(session, profile, payload)
    return to_profile_response(updated)


@router.post("/avatar", response_model=ProfileResponse)
async def post_avatar(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
    storage: PrivateStorageService = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
) -> ProfileResponse:
    data = await file.read()
    updated = await upload_profile_avatar(
        session=session,
        profile=profile,
        storage=storage,
        settings=settings,
        data=data,
        content_type=file.content_type or "application/octet-stream",
    )
    return to_profile_response(updated)


@router.get("/avatar")
async def stream_avatar(
    profile: Profile = Depends(get_current_profile),
    storage: PrivateStorageService = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    content, media_type = await download_profile_avatar(
        profile=profile,
        storage=storage,
        settings=settings,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/avatar", response_model=ProfileResponse)
async def delete_avatar(
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
    storage: PrivateStorageService = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
) -> ProfileResponse:
    updated = await remove_profile_avatar(
        session=session,
        profile=profile,
        storage=storage,
        settings=settings,
    )
    return to_profile_response(updated)

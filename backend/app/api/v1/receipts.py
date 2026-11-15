"""API routes for Receipt Scanner pipeline (/api/v1/receipts)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.receipt.schemas import EditableReceiptDraft
from app.api.deps import get_app_settings, get_current_profile, get_current_user_id, get_storage
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.profile import Profile
from app.schemas.purchase import PurchaseResponse
from app.schemas.receipt import (
    ReceiptConfirmRequest,
    ReceiptResultResponse,
    ReceiptStatusResponse,
    ReceiptSummaryResponse,
)
from app.services.receipt_service import (
    cancel_receipt,
    confirm_receipt_to_purchase,
    delete_receipt,
    download_receipt_file,
    get_receipt_result,
    get_receipt_status,
    list_receipts,
    retry_failed_receipt,
    update_receipt_draft,
    upload_receipt,
)
from app.services.storage_service import PrivateStorageService

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.get("", response_model=list[ReceiptSummaryResponse])
async def get_all_receipts(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ReceiptSummaryResponse]:
    return await list_receipts(
        session,
        user_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/upload",
    response_model=ReceiptSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_receipt_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
    storage: PrivateStorageService = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
) -> ReceiptSummaryResponse:
    data = await file.read()
    return await upload_receipt(
        session=session,
        user_id=user_id,
        storage=storage,
        settings=settings,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )


@router.get("/{receipt_id}/status", response_model=ReceiptStatusResponse)
async def read_receipt_status(
    receipt_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ReceiptStatusResponse:
    return await get_receipt_status(session, user_id, receipt_id)


@router.get("/{receipt_id}/result", response_model=ReceiptResultResponse)
async def read_receipt_result(
    receipt_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ReceiptResultResponse:
    return await get_receipt_result(session, user_id, receipt_id)


@router.get("/{receipt_id}/file")
async def stream_receipt_file(
    receipt_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
    storage: PrivateStorageService = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    content, media_type = await download_receipt_file(
        session=session,
        user_id=user_id,
        receipt_id=receipt_id,
        storage=storage,
        settings=settings,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.patch("/{receipt_id}/draft", response_model=ReceiptResultResponse)
async def patch_receipt_draft(
    receipt_id: uuid.UUID,
    payload: EditableReceiptDraft,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ReceiptResultResponse:
    return await update_receipt_draft(session, user_id, receipt_id, payload)


@router.post("/{receipt_id}/retry", response_model=ReceiptStatusResponse)
async def post_receipt_retry(
    receipt_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ReceiptStatusResponse:
    return await retry_failed_receipt(session, user_id, receipt_id)


@router.post("/{receipt_id}/cancel", response_model=ReceiptStatusResponse)
async def post_receipt_cancel(
    receipt_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ReceiptStatusResponse:
    return await cancel_receipt(session, user_id, receipt_id)


@router.post(
    "/{receipt_id}/confirm",
    response_model=PurchaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_receipt_confirm(
    receipt_id: uuid.UUID,
    payload: ReceiptConfirmRequest,
    session: AsyncSession = Depends(get_db_session),
    profile: Profile = Depends(get_current_profile),
) -> PurchaseResponse:
    return await confirm_receipt_to_purchase(session, profile, receipt_id, payload)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_receipt(
    receipt_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
    storage: PrivateStorageService = Depends(get_storage),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    await delete_receipt(
        session=session,
        user_id=user_id,
        receipt_id=receipt_id,
        storage=storage,
        settings=settings,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

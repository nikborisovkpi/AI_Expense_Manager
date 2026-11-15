"""API routes for Purchases and Purchase Items (/api/v1/purchases, /api/v1/purchase-items)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db_session
from app.schemas.purchase import (
    PurchaseCreateRequest,
    PurchaseItemCreateInput,
    PurchaseItemResponse,
    PurchaseItemUpdateRequest,
    PurchaseResponse,
    PurchaseUpdateRequest,
)
from app.services.purchase_service import (
    add_item_to_purchase,
    create_manual_purchase,
    delete_purchase,
    delete_purchase_item,
    get_purchase_detail,
    list_purchases,
    update_purchase,
    update_purchase_item,
)

router = APIRouter()


@router.get("/purchases", response_model=list[PurchaseResponse], tags=["purchases"])
async def get_purchases(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    store_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    currency: str | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[PurchaseResponse]:
    return await list_purchases(
        session,
        user_id,
        date_from=date_from,
        date_to=date_to,
        store_id=store_id,
        category_id=category_id,
        product_id=product_id,
        currency=currency,
        q=q,
    )


@router.post(
    "/purchases",
    response_model=PurchaseResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["purchases"],
)
async def post_purchase(
    payload: PurchaseCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PurchaseResponse:
    return await create_manual_purchase(session, user_id, payload)


@router.get("/purchases/{purchase_id}", response_model=PurchaseResponse, tags=["purchases"])
async def get_purchase(
    purchase_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PurchaseResponse:
    return await get_purchase_detail(session, user_id, purchase_id)


@router.patch("/purchases/{purchase_id}", response_model=PurchaseResponse, tags=["purchases"])
async def patch_purchase(
    purchase_id: uuid.UUID,
    payload: PurchaseUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PurchaseResponse:
    return await update_purchase(session, user_id, purchase_id, payload)


@router.delete(
    "/purchases/{purchase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["purchases"],
)
async def remove_purchase(
    purchase_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> Response:
    await delete_purchase(session, user_id, purchase_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/purchases/{purchase_id}/items",
    response_model=list[PurchaseItemResponse],
    tags=["purchase-items"],
)
async def get_purchase_items(
    purchase_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[PurchaseItemResponse]:
    detail = await get_purchase_detail(session, user_id, purchase_id)
    return detail.items


@router.post(
    "/purchases/{purchase_id}/items",
    response_model=PurchaseItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["purchase-items"],
)
async def post_purchase_item(
    purchase_id: uuid.UUID,
    payload: PurchaseItemCreateInput,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PurchaseItemResponse:
    return await add_item_to_purchase(session, user_id, purchase_id, payload)


@router.patch(
    "/purchase-items/{item_id}",
    response_model=PurchaseItemResponse,
    tags=["purchase-items"],
)
async def patch_purchase_item(
    item_id: uuid.UUID,
    payload: PurchaseItemUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PurchaseItemResponse:
    return await update_purchase_item(session, user_id, item_id, payload)


@router.delete(
    "/purchase-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["purchase-items"],
)
async def remove_purchase_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> Response:
    await delete_purchase_item(session, user_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""API routes for Shopping Lists (/api/v1/shopping-lists, /api/v1/shopping-list-items)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db_session
from app.schemas.shopping_list import (
    ShoppingListCreateRequest,
    ShoppingListItemCreateRequest,
    ShoppingListItemResponse,
    ShoppingListItemUpdateRequest,
    ShoppingListResponse,
    ShoppingListUpdateRequest,
)
from app.services.shopping_list_service import (
    add_shopping_list_item,
    create_shopping_list,
    delete_shopping_list,
    delete_shopping_list_item,
    get_shopping_list_detail,
    list_shopping_lists,
    update_shopping_list,
    update_shopping_list_item,
)

router = APIRouter()


@router.get("/shopping-lists", response_model=list[ShoppingListResponse], tags=["shopping-lists"])
async def get_lists(
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ShoppingListResponse]:
    return await list_shopping_lists(session, user_id)


@router.post(
    "/shopping-lists",
    response_model=ShoppingListResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["shopping-lists"],
)
async def post_list(
    payload: ShoppingListCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ShoppingListResponse:
    return await create_shopping_list(session, user_id, payload)


@router.get(
    "/shopping-lists/{list_id}",
    response_model=ShoppingListResponse,
    tags=["shopping-lists"],
)
async def get_list(
    list_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ShoppingListResponse:
    return await get_shopping_list_detail(session, user_id, list_id)


@router.patch(
    "/shopping-lists/{list_id}",
    response_model=ShoppingListResponse,
    tags=["shopping-lists"],
)
async def patch_list(
    list_id: uuid.UUID,
    payload: ShoppingListUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ShoppingListResponse:
    return await update_shopping_list(session, user_id, list_id, payload)


@router.delete(
    "/shopping-lists/{list_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["shopping-lists"],
)
async def remove_list(
    list_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> Response:
    await delete_shopping_list(session, user_id, list_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/shopping-lists/{list_id}/items",
    response_model=ShoppingListItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["shopping-lists"],
)
async def post_list_item(
    list_id: uuid.UUID,
    payload: ShoppingListItemCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ShoppingListItemResponse:
    return await add_shopping_list_item(session, user_id, list_id, payload)


@router.patch(
    "/shopping-list-items/{item_id}",
    response_model=ShoppingListItemResponse,
    tags=["shopping-lists"],
)
async def patch_list_item(
    item_id: uuid.UUID,
    payload: ShoppingListItemUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ShoppingListItemResponse:
    return await update_shopping_list_item(session, user_id, item_id, payload)


@router.delete(
    "/shopping-list-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["shopping-lists"],
)
async def remove_list_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> Response:
    await delete_shopping_list_item(session, user_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

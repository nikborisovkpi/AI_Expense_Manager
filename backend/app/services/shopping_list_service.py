"""Shopping lists and items service with automatic price estimation from purchase history."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SupportedCurrency
from app.core.errors import NotFoundError
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseItem
from app.models.shopping_list import ShoppingList, ShoppingListItem
from app.models.store import Store
from app.repositories.base import BaseRepository
from app.schemas.shopping_list import (
    ShoppingListCreateRequest,
    ShoppingListItemCreateRequest,
    ShoppingListItemResponse,
    ShoppingListItemUpdateRequest,
    ShoppingListResponse,
    ShoppingListStatus,
    ShoppingListUpdateRequest,
)
from app.services.pricing_service import quantize_money


def _to_item_response(item: ShoppingListItem) -> ShoppingListItemResponse:
    est_total = (
        quantize_money(item.estimated_price * item.quantity)
        if item.estimated_price is not None
        else None
    )
    return ShoppingListItemResponse(
        id=item.id,
        shopping_list_id=item.shopping_list_id,
        product_id=item.product_id,
        product_name=item.product_name,
        quantity=item.quantity,
        unit=item.unit,
        estimated_price=item.estimated_price,
        estimated_line_total=est_total,
        is_estimated=True,
        is_purchased=item.is_purchased,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _build_list_response(
    session: AsyncSession,
    shopping_list: ShoppingList,
) -> ShoppingListResponse:
    items = list(
        (
            await session.scalars(
                select(ShoppingListItem)
                .where(ShoppingListItem.shopping_list_id == shopping_list.id)
                .order_by(ShoppingListItem.created_at.asc())
            )
        ).all()
    )
    store_name: str | None = None
    if shopping_list.store_id is not None:
        st = await session.scalar(select(Store).where(Store.id == shopping_list.store_id))
        if st is not None:
            store_name = st.display_name

    item_responses = [_to_item_response(i) for i in items]
    est_total = quantize_money(
        sum(
            (r.estimated_line_total for r in item_responses if r.estimated_line_total is not None),
            Decimal("0.00"),
        )
    )
    missing_est = sum(1 for r in item_responses if r.estimated_price is None)

    return ShoppingListResponse(
        id=shopping_list.id,
        store_id=shopping_list.store_id,
        store_display_name=store_name,
        name=shopping_list.name,
        currency=cast(SupportedCurrency, shopping_list.currency),
        status=cast(ShoppingListStatus, shopping_list.status),
        is_estimated=True,
        estimated_total=est_total,
        items_without_estimate_count=missing_est,
        items=item_responses,
        created_at=shopping_list.created_at,
        updated_at=shopping_list.updated_at,
    )


async def _estimate_unit_price_from_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    currency: str,
    store_id: uuid.UUID | None,
) -> Decimal | None:
    stmt = (
        select(PurchaseItem.unit_price)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .where(
            Purchase.user_id == user_id,
            Purchase.currency == currency,
            PurchaseItem.product_id == product_id,
        )
        .order_by(Purchase.purchase_date.desc())
        .limit(1)
    )
    if store_id is not None:
        store_price = await session.scalar(stmt.where(Purchase.store_id == store_id))
        if store_price is not None:
            return quantize_money(store_price)
    any_store_price = await session.scalar(stmt)
    return quantize_money(any_store_price) if any_store_price is not None else None


async def list_shopping_lists(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[ShoppingListResponse]:
    repo = BaseRepository(session, user_id, ShoppingList)
    rows = await repo.list_matching(repo.scoped_select().order_by(ShoppingList.created_at.desc()))
    return [await _build_list_response(session, r) for r in rows]


async def get_shopping_list_detail(
    session: AsyncSession,
    user_id: uuid.UUID,
    list_id: uuid.UUID,
) -> ShoppingListResponse:
    repo = BaseRepository(session, user_id, ShoppingList)
    sl = await repo.get_by_id_or_raise(list_id)
    return await _build_list_response(session, sl)


async def create_shopping_list(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: ShoppingListCreateRequest,
) -> ShoppingListResponse:
    repo = BaseRepository(session, user_id, ShoppingList)
    if payload.store_id is not None:
        await repo.verify_owned_reference(Store, payload.store_id)
    sl = await repo.create(
        name=payload.name.strip(),
        store_id=payload.store_id,
        currency=payload.currency,
        status="active",
    )
    await session.commit()
    await session.refresh(sl)
    return await _build_list_response(session, sl)


async def update_shopping_list(
    session: AsyncSession,
    user_id: uuid.UUID,
    list_id: uuid.UUID,
    payload: ShoppingListUpdateRequest,
) -> ShoppingListResponse:
    repo = BaseRepository(session, user_id, ShoppingList)
    sl = await repo.get_by_id_or_raise(list_id)
    if payload.store_id is not None:
        await repo.verify_owned_reference(Store, payload.store_id)
        sl.store_id = payload.store_id
    if payload.name is not None:
        sl.name = payload.name.strip()
    if payload.currency is not None:
        sl.currency = payload.currency
    if payload.status is not None:
        sl.status = payload.status
    await session.commit()
    await session.refresh(sl)
    return await _build_list_response(session, sl)


async def delete_shopping_list(
    session: AsyncSession,
    user_id: uuid.UUID,
    list_id: uuid.UUID,
) -> None:
    repo = BaseRepository(session, user_id, ShoppingList)
    await repo.delete(list_id)
    await session.commit()


async def add_shopping_list_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    list_id: uuid.UUID,
    payload: ShoppingListItemCreateRequest,
) -> ShoppingListItemResponse:
    repo = BaseRepository(session, user_id, ShoppingList)
    sl = await repo.get_by_id_or_raise(list_id)
    if payload.product_id is not None:
        await repo.verify_owned_reference(Product, payload.product_id)

    est_price = (
        quantize_money(payload.estimated_price) if payload.estimated_price is not None else None
    )
    if est_price is None and payload.product_id is not None:
        est_price = await _estimate_unit_price_from_history(
            session,
            user_id,
            payload.product_id,
            sl.currency,
            sl.store_id,
        )

    item = ShoppingListItem(
        shopping_list_id=sl.id,
        product_id=payload.product_id,
        product_name=payload.product_name.strip(),
        quantity=payload.quantity,
        unit=payload.unit,
        estimated_price=est_price,
        is_purchased=False,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _to_item_response(item)


async def _get_owned_list_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
) -> ShoppingListItem:
    stmt = (
        select(ShoppingListItem)
        .join(ShoppingList, ShoppingList.id == ShoppingListItem.shopping_list_id)
        .where(ShoppingListItem.id == item_id, ShoppingList.user_id == user_id)
    )
    item = await session.scalar(stmt)
    if item is None:
        raise NotFoundError("Shopping list item not found")
    return item


async def update_shopping_list_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ShoppingListItemUpdateRequest,
) -> ShoppingListItemResponse:
    item = await _get_owned_list_item(session, user_id, item_id)
    repo = BaseRepository(session, user_id, ShoppingList)
    if payload.product_id is not None:
        await repo.verify_owned_reference(Product, payload.product_id)
        item.product_id = payload.product_id
    if payload.product_name is not None:
        item.product_name = payload.product_name.strip()
    if payload.quantity is not None:
        item.quantity = payload.quantity
    if payload.unit is not None:
        item.unit = payload.unit
    if payload.estimated_price is not None:
        item.estimated_price = quantize_money(payload.estimated_price)
    if payload.is_purchased is not None:
        item.is_purchased = payload.is_purchased

    await session.commit()
    await session.refresh(item)
    return _to_item_response(item)


async def delete_shopping_list_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
) -> None:
    item = await _get_owned_list_item(session, user_id, item_id)
    await session.delete(item)
    await session.commit()

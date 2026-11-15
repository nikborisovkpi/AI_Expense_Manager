"""Domain service for confirmed Purchases and Purchase Items."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SupportedCurrency
from app.core.errors import NotFoundError
from app.db.base import utcnow
from app.models.category import Category
from app.models.insight import DashboardInsight
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseItem
from app.models.receipt import Receipt
from app.models.store import Store
from app.repositories.base import BaseRepository
from app.schemas.purchase import (
    PurchaseCreateRequest,
    PurchaseItemCreateInput,
    PurchaseItemResponse,
    PurchaseItemUpdateRequest,
    PurchaseResponse,
    PurchaseSource,
    PurchaseUpdateRequest,
)
from app.services.catalog_service import get_visible_category_or_raise
from app.services.pricing_service import (
    ItemPriceInput,
    allocate_purchase_items_pricing,
    normalize_measurement,
    quantize_money,
)


async def mark_dashboard_insights_stale(
    session: AsyncSession,
    user_id: uuid.UUID,
    currency: str,
) -> None:
    """Increment data_version and mark cached dashboard insights stale after purchase mutations."""
    existing = await session.scalar(
        select(DashboardInsight).where(
            DashboardInsight.user_id == user_id,
            DashboardInsight.insight_type == "overview",
            DashboardInsight.currency == currency,
        )
    )
    if existing is not None:
        existing.data_version += 1
        existing.status = "stale"
        existing.last_purchase_at = utcnow()
    else:
        session.add(
            DashboardInsight(
                user_id=user_id,
                insight_type="overview",
                currency=currency,
                content={},
                source_purchase_ids=[],
                data_version=1,
                status="stale",
                last_purchase_at=utcnow(),
            )
        )


async def _resolve_item_snapshots(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_input: PurchaseItemCreateInput,
) -> tuple[
    Product | None,
    uuid.UUID | None,
    uuid.UUID | None,
    str | None,
    str,
    Decimal,
]:
    repo = BaseRepository(session, user_id, Purchase)
    product: Product | None = None
    if item_input.product_id is not None:
        product = await repo.verify_owned_reference(Product, item_input.product_id)

    cat_id = item_input.category_id or (product.category_id if product else None)
    cat: Category | None = None
    if cat_id is not None:
        cat = await get_visible_category_or_raise(session, user_id, cat_id)

    if product is not None:
        std_unit = product.standard_unit
        std_qty = product.standard_quantity
    else:
        std_unit, std_qty = normalize_measurement(Decimal("1"), item_input.unit)

    return (
        product,
        cat.id if cat else None,
        cat.parent_id if cat else None,
        cat.name if cat else None,
        std_unit,
        std_qty,
    )


async def _recompute_purchase_item_allocations(
    session: AsyncSession,
    purchase: Purchase,
) -> list[PurchaseItem]:
    items = list(
        (
            await session.scalars(
                select(PurchaseItem)
                .where(PurchaseItem.purchase_id == purchase.id)
                .order_by(PurchaseItem.created_at.asc(), PurchaseItem.id.asc())
            )
        ).all()
    )
    if not items:
        return []

    inputs = [
        ItemPriceInput(
            quantity=i.quantity,
            unit_price=i.unit_price,
            discount_amount=i.discount_amount,
            standard_quantity=i.standard_quantity_snapshot,
        )
        for i in items
    ]
    priced = allocate_purchase_items_pricing(items=inputs, final_amount=purchase.amount)
    for item_row, calc in zip(items, priced, strict=True):
        item_row.total_price = calc.total_price
        item_row.effective_total_price = calc.effective_total_price
        item_row.regular_standard_unit_price = calc.regular_standard_unit_price
        item_row.paid_standard_unit_price = calc.paid_standard_unit_price
    await session.flush()
    return items


async def build_purchase_response(
    session: AsyncSession,
    purchase: Purchase,
    *,
    include_items: bool = True,
) -> PurchaseResponse:
    items = list(
        (
            await session.scalars(
                select(PurchaseItem)
                .where(PurchaseItem.purchase_id == purchase.id)
                .order_by(PurchaseItem.created_at.asc(), PurchaseItem.id.asc())
            )
        ).all()
    )
    store_name: str | None = None
    if purchase.store_id is not None:
        store = await session.scalar(select(Store).where(Store.id == purchase.store_id))
        if store is not None:
            store_name = store.display_name

    receipt = await session.scalar(
        select(Receipt).where(
            Receipt.purchase_id == purchase.id,
            Receipt.user_id == purchase.user_id,
        )
    )

    return PurchaseResponse(
        id=purchase.id,
        store_id=purchase.store_id,
        store_display_name=store_name,
        title=purchase.title,
        subtotal=purchase.subtotal,
        discounts_total=purchase.discounts_total,
        tax_total=purchase.tax_total,
        tax_included=purchase.tax_included,
        container_deposit_total=purchase.container_deposit_total,
        rounding_adjustment=purchase.rounding_adjustment,
        amount=purchase.amount,
        currency=cast(SupportedCurrency, purchase.currency),
        purchase_date=purchase.purchase_date,
        description=purchase.description,
        source=cast(PurchaseSource, purchase.source),
        item_count=len(items),
        receipt_id=receipt.id if receipt else None,
        receipt_status=receipt.status if receipt else None,
        items=[PurchaseItemResponse.model_validate(i) for i in items] if include_items else [],
        created_at=purchase.created_at,
        updated_at=purchase.updated_at,
    )


async def list_purchases(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    store_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    currency: str | None = None,
    q: str | None = None,
) -> list[PurchaseResponse]:
    repo = BaseRepository(session, user_id, Purchase)
    stmt = repo.scoped_select()
    if date_from is not None:
        stmt = stmt.where(Purchase.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Purchase.purchase_date <= date_to)
    if store_id is not None:
        stmt = stmt.where(Purchase.store_id == store_id)
    if currency is not None:
        stmt = stmt.where(Purchase.currency == currency)
    if q:
        stmt = stmt.where(Purchase.title.ilike(f"%{q.strip()}%"))

    if category_id is not None or product_id is not None:
        item_sub = select(PurchaseItem.purchase_id).where(PurchaseItem.purchase_id == Purchase.id)
        if category_id is not None:
            item_sub = item_sub.where(
                (PurchaseItem.category_id_snapshot == category_id)
                | (PurchaseItem.parent_category_id_snapshot == category_id)
            )
        if product_id is not None:
            item_sub = item_sub.where(PurchaseItem.product_id == product_id)
        stmt = stmt.where(item_sub.exists())

    stmt = stmt.order_by(Purchase.purchase_date.desc())
    purchases = await repo.list_matching(stmt)
    return [await build_purchase_response(session, p, include_items=False) for p in purchases]


async def create_manual_purchase(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: PurchaseCreateRequest,
    *,
    source: PurchaseSource = "manual",
) -> PurchaseResponse:
    repo = BaseRepository(session, user_id, Purchase)
    if payload.idempotency_key:
        existing = await repo.scalar_one_or_none(
            repo.scoped_select().where(Purchase.idempotency_key == payload.idempotency_key)
        )
        if existing is not None:
            return await build_purchase_response(session, existing)

    if payload.store_id is not None:
        await repo.verify_owned_reference(Store, payload.store_id)

    purchase = await repo.create(
        store_id=payload.store_id,
        title=payload.title.strip(),
        subtotal=quantize_money(payload.subtotal),
        discounts_total=quantize_money(payload.discounts_total),
        tax_total=quantize_money(payload.tax_total),
        tax_included=payload.tax_included,
        container_deposit_total=quantize_money(payload.container_deposit_total),
        rounding_adjustment=quantize_money(payload.rounding_adjustment),
        amount=quantize_money(payload.amount),
        currency=payload.currency,
        purchase_date=payload.purchase_date,
        description=payload.description,
        source=source,
        idempotency_key=payload.idempotency_key,
    )

    resolved_meta = []
    price_inputs: list[ItemPriceInput] = []
    for item_in in payload.items:
        meta = await _resolve_item_snapshots(session, user_id, item_in)
        resolved_meta.append((item_in, meta))
        price_inputs.append(
            ItemPriceInput(
                quantity=item_in.quantity,
                unit_price=item_in.unit_price,
                discount_amount=item_in.discount_amount,
                total_price=item_in.total_price,
                standard_quantity=meta[5],
            )
        )

    priced_items = allocate_purchase_items_pricing(
        items=price_inputs,
        final_amount=purchase.amount,
    )
    for (item_in, meta), calc in zip(resolved_meta, priced_items, strict=True):
        prod, cat_id, parent_cat_id, cat_name, std_unit, std_qty = meta
        session.add(
            PurchaseItem(
                purchase_id=purchase.id,
                product_id=prod.id if prod else None,
                raw_name=item_in.raw_name.strip(),
                quantity=item_in.quantity,
                unit=item_in.unit,
                unit_price=item_in.unit_price,
                discount_amount=quantize_money(item_in.discount_amount),
                total_price=calc.total_price,
                effective_total_price=calc.effective_total_price,
                category_id_snapshot=cat_id,
                parent_category_id_snapshot=parent_cat_id,
                category_name_snapshot=cat_name,
                standard_unit_snapshot=std_unit,
                standard_quantity_snapshot=std_qty,
                regular_standard_unit_price=calc.regular_standard_unit_price,
                paid_standard_unit_price=calc.paid_standard_unit_price,
            )
        )

    await mark_dashboard_insights_stale(session, user_id, purchase.currency)
    await session.commit()
    await session.refresh(purchase)
    return await build_purchase_response(session, purchase)


async def get_purchase_detail(
    session: AsyncSession,
    user_id: uuid.UUID,
    purchase_id: uuid.UUID,
) -> PurchaseResponse:
    repo = BaseRepository(session, user_id, Purchase)
    purchase = await repo.get_by_id_or_raise(purchase_id)
    return await build_purchase_response(session, purchase)


async def update_purchase(
    session: AsyncSession,
    user_id: uuid.UUID,
    purchase_id: uuid.UUID,
    payload: PurchaseUpdateRequest,
) -> PurchaseResponse:
    repo = BaseRepository(session, user_id, Purchase)
    purchase = await repo.get_by_id_or_raise(purchase_id)

    if payload.store_id is not None:
        await repo.verify_owned_reference(Store, payload.store_id)
        purchase.store_id = payload.store_id
    if payload.title is not None:
        purchase.title = payload.title.strip()
    if payload.subtotal is not None:
        purchase.subtotal = quantize_money(payload.subtotal)
    if payload.discounts_total is not None:
        purchase.discounts_total = quantize_money(payload.discounts_total)
    if payload.tax_total is not None:
        purchase.tax_total = quantize_money(payload.tax_total)
    if payload.tax_included is not None:
        purchase.tax_included = payload.tax_included
    if payload.container_deposit_total is not None:
        purchase.container_deposit_total = quantize_money(payload.container_deposit_total)
    if payload.rounding_adjustment is not None:
        purchase.rounding_adjustment = quantize_money(payload.rounding_adjustment)
    if payload.amount is not None:
        purchase.amount = quantize_money(payload.amount)
    if payload.currency is not None:
        purchase.currency = payload.currency
    if payload.purchase_date is not None:
        purchase.purchase_date = payload.purchase_date
    if payload.description is not None:
        purchase.description = payload.description

    await _recompute_purchase_item_allocations(session, purchase)
    await mark_dashboard_insights_stale(session, user_id, purchase.currency)
    await session.commit()
    await session.refresh(purchase)
    return await build_purchase_response(session, purchase)


async def delete_purchase(
    session: AsyncSession,
    user_id: uuid.UUID,
    purchase_id: uuid.UUID,
) -> None:
    repo = BaseRepository(session, user_id, Purchase)
    purchase = await repo.get_by_id_or_raise(purchase_id)
    currency = purchase.currency

    # Unlink any attached receipt and return it to needs_review without deleting the receipt
    await session.execute(
        update(Receipt)
        .where(Receipt.user_id == user_id, Receipt.purchase_id == purchase.id)
        .values(purchase_id=None, status="needs_review")
    )
    await session.delete(purchase)
    await mark_dashboard_insights_stale(session, user_id, currency)
    await session.commit()


async def add_item_to_purchase(
    session: AsyncSession,
    user_id: uuid.UUID,
    purchase_id: uuid.UUID,
    payload: PurchaseItemCreateInput,
) -> PurchaseItemResponse:
    repo = BaseRepository(session, user_id, Purchase)
    purchase = await repo.get_by_id_or_raise(purchase_id)
    prod, cat_id, parent_cat_id, cat_name, std_unit, std_qty = await _resolve_item_snapshots(
        session, user_id, payload
    )

    line_total = quantize_money(payload.quantity * payload.unit_price - payload.discount_amount)
    item = PurchaseItem(
        purchase_id=purchase.id,
        product_id=prod.id if prod else None,
        raw_name=payload.raw_name.strip(),
        quantity=payload.quantity,
        unit=payload.unit,
        unit_price=payload.unit_price,
        discount_amount=quantize_money(payload.discount_amount),
        total_price=line_total,
        effective_total_price=line_total,
        category_id_snapshot=cat_id,
        parent_category_id_snapshot=parent_cat_id,
        category_name_snapshot=cat_name,
        standard_unit_snapshot=std_unit,
        standard_quantity_snapshot=std_qty,
    )
    session.add(item)
    await session.flush()
    await _recompute_purchase_item_allocations(session, purchase)
    await mark_dashboard_insights_stale(session, user_id, purchase.currency)
    await session.commit()
    await session.refresh(item)
    return PurchaseItemResponse.model_validate(item)


async def _get_owned_purchase_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
) -> tuple[PurchaseItem, Purchase]:
    stmt = (
        select(PurchaseItem, Purchase)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .where(PurchaseItem.id == item_id, Purchase.user_id == user_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFoundError("Purchase item not found")
    return row[0], row[1]


async def update_purchase_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: PurchaseItemUpdateRequest,
) -> PurchaseItemResponse:
    item, purchase = await _get_owned_purchase_item(session, user_id, item_id)
    repo = BaseRepository(session, user_id, Purchase)

    if payload.product_id is not None:
        prod = cast(Product, await repo.verify_owned_reference(Product, payload.product_id))
        item.product_id = prod.id
        item.standard_unit_snapshot = prod.standard_unit
        item.standard_quantity_snapshot = prod.standard_quantity
    if payload.category_id is not None:
        cat = await get_visible_category_or_raise(session, user_id, payload.category_id)
        item.category_id_snapshot = cat.id
        item.parent_category_id_snapshot = cat.parent_id
        item.category_name_snapshot = cat.name
    if payload.raw_name is not None:
        item.raw_name = payload.raw_name.strip()
    if payload.quantity is not None:
        item.quantity = payload.quantity
    if payload.unit is not None:
        item.unit = payload.unit
    if payload.unit_price is not None:
        item.unit_price = payload.unit_price
    if payload.discount_amount is not None:
        item.discount_amount = quantize_money(payload.discount_amount)

    await _recompute_purchase_item_allocations(session, purchase)
    await mark_dashboard_insights_stale(session, user_id, purchase.currency)
    await session.commit()
    await session.refresh(item)
    return PurchaseItemResponse.model_validate(item)


async def delete_purchase_item(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
) -> None:
    item, purchase = await _get_owned_purchase_item(session, user_id, item_id)
    await session.delete(item)
    await session.flush()
    await _recompute_purchase_item_allocations(session, purchase)
    await mark_dashboard_insights_stale(session, user_id, purchase.currency)
    await session.commit()

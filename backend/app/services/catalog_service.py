"""Domain service for Categories, Stores, Products, Aliases, Price History, and Store Comparison."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SupportedCurrency
from app.core.errors import ForbiddenError, NotFoundError, ValidationDomainError
from app.db.base import utcnow
from app.db.seed import slugify
from app.models.category import Category
from app.models.product import Product, ProductAlias
from app.models.purchase import Purchase, PurchaseItem
from app.models.store import Store, StoreChain
from app.repositories.base import BaseRepository
from app.schemas.catalog import (
    CategoryCreateRequest,
    CategoryResponse,
    CategoryTreeNode,
    CategoryUpdateRequest,
    PriceObservationPoint,
    ProductCreateRequest,
    ProductPriceHistoryResponse,
    ProductStoreComparisonResponse,
    ProductUpdateRequest,
    StoreCreateRequest,
    StorePriceComparisonRow,
    StoreResponse,
    StoreUpdateRequest,
)
from app.services.pricing_service import normalize_measurement, quantize_unit_price


# --- Categories ---
async def list_visible_categories(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_inactive: bool = False,
) -> list[Category]:
    stmt = select(Category).where(or_(Category.is_system.is_(True), Category.user_id == user_id))
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    stmt = stmt.order_by(Category.is_system.desc(), Category.name.asc())
    return list((await session.scalars(stmt)).all())


async def build_category_tree(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[CategoryTreeNode]:
    cats = await list_visible_categories(session, user_id, include_inactive=False)
    roots = [c for c in cats if c.parent_id is None]
    children_map: dict[uuid.UUID, list[CategoryResponse]] = {}
    for c in cats:
        if c.parent_id is not None:
            children_map.setdefault(c.parent_id, []).append(CategoryResponse.model_validate(c))

    tree: list[CategoryTreeNode] = []
    for root in roots:
        node = CategoryTreeNode.model_validate(root)
        node.children = children_map.get(root.id, [])
        tree.append(node)
    return tree


async def get_visible_category_or_raise(
    session: AsyncSession,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
) -> Category:
    cat = await session.scalar(select(Category).where(Category.id == category_id))
    if cat is None:
        raise NotFoundError("Category not found")
    if not cat.is_system and cat.user_id != user_id:
        raise NotFoundError("Category not found")
    return cat


async def create_custom_category(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: CategoryCreateRequest,
) -> Category:
    macro_group: str = payload.macro_group
    if payload.parent_id is not None:
        parent = await get_visible_category_or_raise(session, user_id, payload.parent_id)
        if parent.parent_id is not None:
            raise ValidationDomainError("Category hierarchy supports at most 2 levels")
        macro_group = parent.macro_group

    repo = BaseRepository(session, user_id, Category)
    cat = await repo.create(
        parent_id=payload.parent_id,
        is_system=False,
        macro_group=macro_group,
        name=payload.name.strip(),
        slug=slugify(payload.name),
        description=payload.description,
        icon=payload.icon,
        is_active=True,
    )
    await session.commit()
    await session.refresh(cat)
    return cat


async def update_custom_category(
    session: AsyncSession,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: CategoryUpdateRequest,
) -> Category:
    cat = await session.scalar(select(Category).where(Category.id == category_id))
    if cat is None:
        raise NotFoundError("Category not found")
    if cat.is_system:
        raise ForbiddenError("System categories are read-only and cannot be modified")
    if cat.user_id != user_id:
        raise NotFoundError("Category not found")

    if payload.name is not None:
        cat.name = payload.name.strip()
        cat.slug = slugify(payload.name)
    if payload.macro_group is not None and cat.parent_id is None:
        cat.macro_group = payload.macro_group
    if payload.description is not None:
        cat.description = payload.description
    if payload.icon is not None:
        cat.icon = payload.icon
    if payload.is_active is not None:
        cat.is_active = payload.is_active

    await session.commit()
    await session.refresh(cat)
    return cat


async def deactivate_custom_category(
    session: AsyncSession,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
) -> Category:
    cat = await session.scalar(select(Category).where(Category.id == category_id))
    if cat is None:
        raise NotFoundError("Category not found")
    if cat.is_system:
        raise ForbiddenError("System categories cannot be deleted")
    if cat.user_id != user_id:
        raise NotFoundError("Category not found")

    cat.is_active = False
    await session.commit()
    await session.refresh(cat)
    return cat


# --- Store Chains & Stores ---
async def list_store_chains(session: AsyncSession) -> list[StoreChain]:
    stmt = select(StoreChain).order_by(
        StoreChain.is_fallback.asc(), StoreChain.canonical_name.asc()
    )
    return list((await session.scalars(stmt)).all())


async def resolve_store_chain(
    session: AsyncSession,
    store_chain_id: uuid.UUID | None,
) -> StoreChain:
    if store_chain_id is not None:
        chain = await session.scalar(select(StoreChain).where(StoreChain.id == store_chain_id))
        if chain is None:
            raise NotFoundError("Global store chain not found")
        return chain

    fallback = await session.scalar(select(StoreChain).where(StoreChain.is_fallback.is_(True)))
    if fallback is None:
        raise NotFoundError("Fallback store chain 'other' is missing from database seeds")
    return fallback


def _to_store_response(store: Store, chain: StoreChain) -> StoreResponse:
    return StoreResponse(
        id=store.id,
        store_chain_id=store.store_chain_id,
        chain_slug=chain.slug,
        chain_name=chain.canonical_name,
        display_name=store.display_name,
        branch_name=store.branch_name,
        address=store.address,
        city=store.city,
        country=store.country,
        is_active=store.is_active,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


async def list_user_stores(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_inactive: bool = False,
    store_chain_id: uuid.UUID | None = None,
) -> list[StoreResponse]:
    repo = BaseRepository(session, user_id, Store)
    stmt = repo.scoped_select()
    if not include_inactive:
        stmt = stmt.where(Store.is_active.is_(True))
    if store_chain_id is not None:
        stmt = stmt.where(Store.store_chain_id == store_chain_id)
    stmt = stmt.order_by(Store.display_name.asc())
    stores = await repo.list_matching(stmt)
    if not stores:
        return []
    chains = {c.id: c for c in (await session.scalars(select(StoreChain))).all()}
    return [_to_store_response(s, chains[s.store_chain_id]) for s in stores]


async def get_user_store(
    session: AsyncSession,
    user_id: uuid.UUID,
    store_id: uuid.UUID,
) -> StoreResponse:
    repo = BaseRepository(session, user_id, Store)
    store = await repo.get_by_id_or_raise(store_id)
    chain = await resolve_store_chain(session, store.store_chain_id)
    return _to_store_response(store, chain)


async def create_user_store(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: StoreCreateRequest,
) -> StoreResponse:
    chain = await resolve_store_chain(session, payload.store_chain_id)
    repo = BaseRepository(session, user_id, Store)
    store = await repo.create(
        store_chain_id=chain.id,
        display_name=payload.display_name.strip(),
        branch_name=payload.branch_name,
        address=payload.address,
        city=payload.city,
        country=payload.country,
        is_active=True,
    )
    await session.commit()
    await session.refresh(store)
    return _to_store_response(store, chain)


async def update_user_store(
    session: AsyncSession,
    user_id: uuid.UUID,
    store_id: uuid.UUID,
    payload: StoreUpdateRequest,
) -> StoreResponse:
    repo = BaseRepository(session, user_id, Store)
    store = await repo.get_by_id_or_raise(store_id)
    if payload.store_chain_id is not None:
        chain = await resolve_store_chain(session, payload.store_chain_id)
        store.store_chain_id = chain.id
    else:
        chain = await resolve_store_chain(session, store.store_chain_id)

    if payload.display_name is not None:
        store.display_name = payload.display_name.strip()
    if payload.branch_name is not None:
        store.branch_name = payload.branch_name
    if payload.address is not None:
        store.address = payload.address
    if payload.city is not None:
        store.city = payload.city
    if payload.country is not None:
        store.country = payload.country

    await session.commit()
    await session.refresh(store)
    return _to_store_response(store, chain)


async def archive_user_store(
    session: AsyncSession,
    user_id: uuid.UUID,
    store_id: uuid.UUID,
) -> StoreResponse:
    repo = BaseRepository(session, user_id, Store)
    store = await repo.get_by_id_or_raise(store_id)
    store.is_active = False
    await session.commit()
    await session.refresh(store)
    chain = await resolve_store_chain(session, store.store_chain_id)
    return _to_store_response(store, chain)


# --- Products & Product Aliases ---
async def list_user_products(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    product_type: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    purchased_from: datetime | None = None,
    purchased_to: datetime | None = None,
    include_inactive: bool = False,
) -> list[Product]:
    repo = BaseRepository(session, user_id, Product)
    stmt = repo.scoped_select()
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Product.normalized_name.ilike(pattern),
                Product.brand.ilike(pattern),
            )
        )
    if category_id is not None:
        child_ids = list(
            (
                await session.scalars(select(Category.id).where(Category.parent_id == category_id))
            ).all()
        )
        stmt = stmt.where(Product.category_id.in_([category_id, *child_ids]))
    if product_type is not None:
        stmt = stmt.where(Product.product_type == product_type)

    if any(v is not None for v in (store_id, min_price, max_price, purchased_from, purchased_to)):
        subq = (
            select(PurchaseItem.product_id)
            .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
            .where(Purchase.user_id == user_id, PurchaseItem.product_id.is_not(None))
        )
        if store_id is not None:
            subq = subq.where(Purchase.store_id == store_id)
        if min_price is not None:
            subq = subq.where(PurchaseItem.unit_price >= min_price)
        if max_price is not None:
            subq = subq.where(PurchaseItem.unit_price <= max_price)
        if purchased_from is not None:
            subq = subq.where(Purchase.purchase_date >= purchased_from)
        if purchased_to is not None:
            subq = subq.where(Purchase.purchase_date <= purchased_to)
        stmt = stmt.where(Product.id.in_(subq))

    stmt = stmt.order_by(Product.normalized_name.asc())
    return await repo.list_matching(stmt)


async def create_user_product(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: ProductCreateRequest,
) -> Product:
    await get_visible_category_or_raise(session, user_id, payload.category_id)
    std_unit, std_qty = normalize_measurement(payload.package_size, payload.package_unit)
    repo = BaseRepository(session, user_id, Product)
    prod = await repo.create(
        category_id=payload.category_id,
        normalized_name=payload.normalized_name.strip(),
        brand=payload.brand.strip() if payload.brand else None,
        product_type=payload.product_type,
        package_size=payload.package_size,
        package_unit=payload.package_unit,
        standard_unit=std_unit,
        standard_quantity=std_qty,
        barcode=payload.barcode,
        description=payload.description,
        is_active=True,
    )
    await session.commit()
    await session.refresh(prod)
    return prod


async def update_user_product(
    session: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductUpdateRequest,
) -> Product:
    repo = BaseRepository(session, user_id, Product)
    prod = await repo.get_by_id_or_raise(product_id)

    if payload.category_id is not None:
        await get_visible_category_or_raise(session, user_id, payload.category_id)
        prod.category_id = payload.category_id
    if payload.normalized_name is not None:
        prod.normalized_name = payload.normalized_name.strip()
    if payload.brand is not None:
        prod.brand = payload.brand.strip() or None
    if payload.product_type is not None:
        prod.product_type = payload.product_type
    if payload.barcode is not None:
        prod.barcode = payload.barcode
    if payload.description is not None:
        prod.description = payload.description

    new_size = payload.package_size if payload.package_size is not None else prod.package_size
    new_unit = payload.package_unit if payload.package_unit is not None else prod.package_unit
    if payload.package_size is not None or payload.package_unit is not None:
        std_unit, std_qty = normalize_measurement(new_size, new_unit)
        prod.package_size = new_size
        prod.package_unit = new_unit
        prod.standard_unit = std_unit
        prod.standard_quantity = std_qty

    await session.commit()
    await session.refresh(prod)
    return prod


async def archive_user_product(
    session: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Product:
    repo = BaseRepository(session, user_id, Product)
    prod = await repo.get_by_id_or_raise(product_id)
    prod.is_active = False
    prod.archived_at = utcnow()
    await session.commit()
    await session.refresh(prod)
    return prod


async def list_product_aliases(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    confirmation_status: str | None = None,
    store_chain_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
) -> list[ProductAlias]:
    repo = BaseRepository(session, user_id, ProductAlias)
    stmt = repo.scoped_select()
    if confirmation_status is not None:
        stmt = stmt.where(ProductAlias.confirmation_status == confirmation_status)
    if store_chain_id is not None:
        stmt = stmt.where(ProductAlias.store_chain_id == store_chain_id)
    if product_id is not None:
        stmt = stmt.where(ProductAlias.product_id == product_id)
    stmt = stmt.order_by(ProductAlias.created_at.desc())
    return await repo.list_matching(stmt)


async def set_alias_confirmation_status(
    session: AsyncSession,
    user_id: uuid.UUID,
    alias_id: uuid.UUID,
    status: Literal["user_confirmed", "rejected"],
) -> ProductAlias:
    repo = BaseRepository(session, user_id, ProductAlias)
    alias = await repo.get_by_id_or_raise(alias_id)
    await repo.verify_owned_reference(Product, alias.product_id)
    alias.confirmation_status = status
    alias.confirmed_by_user_at = utcnow() if status == "user_confirmed" else None
    await session.commit()
    await session.refresh(alias)
    return alias


# --- Price History & Dual-Price Store Comparison ---
async def get_product_price_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
) -> ProductPriceHistoryResponse:
    prod_repo = BaseRepository(session, user_id, Product)
    product = await prod_repo.get_by_id_or_raise(product_id)

    stmt = (
        select(PurchaseItem, Purchase, Store, StoreChain)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .outerjoin(Store, Store.id == Purchase.store_id)
        .outerjoin(StoreChain, StoreChain.id == Store.store_chain_id)
        .where(
            Purchase.user_id == user_id,
            PurchaseItem.product_id == product.id,
            Purchase.currency == currency,
        )
        .order_by(Purchase.purchase_date.asc())
    )
    rows = (await session.execute(stmt)).all()

    points: list[PriceObservationPoint] = []
    reg_prices: list[Decimal] = []
    for item, purchase, store, chain in rows:
        if (
            item.standard_unit_snapshot == product.standard_unit
            and item.regular_standard_unit_price is not None
        ):
            reg_prices.append(item.regular_standard_unit_price)
        points.append(
            PriceObservationPoint(
                purchase_id=purchase.id,
                purchase_item_id=item.id,
                purchase_date=purchase.purchase_date,
                currency=cast(SupportedCurrency, purchase.currency),
                store_id=store.id if store else None,
                store_display_name=store.display_name if store else None,
                chain_slug=chain.slug if chain else None,
                chain_name=chain.canonical_name if chain else None,
                regular_unit_price=item.unit_price,
                paid_effective_total=item.effective_total_price,
                quantity=item.quantity,
                standard_unit=item.standard_unit_snapshot,
                regular_standard_unit_price=item.regular_standard_unit_price,
                paid_standard_unit_price=item.paid_standard_unit_price,
            )
        )

    avg_reg = (
        quantize_unit_price(sum(reg_prices, Decimal("0")) / Decimal(len(reg_prices)))
        if reg_prices
        else None
    )

    return ProductPriceHistoryResponse(
        product_id=product.id,
        product_name=product.normalized_name,
        standard_unit=product.standard_unit,
        currency=currency,
        observation_count=len(points),
        min_regular_standard_price=min(reg_prices) if reg_prices else None,
        max_regular_standard_price=max(reg_prices) if reg_prices else None,
        avg_regular_standard_price=avg_reg,
        latest_regular_standard_price=reg_prices[-1] if reg_prices else None,
        observations=points,
    )


async def compare_product_store_prices(
    session: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    currency: SupportedCurrency = "RON",
    group_by: Literal["chain", "branch"] = "chain",
) -> ProductStoreComparisonResponse:
    """Compare ORIGINAL pre-discount regular standard unit prices across store chains/branches."""
    prod_repo = BaseRepository(session, user_id, Product)
    product = await prod_repo.get_by_id_or_raise(product_id)

    stmt = (
        select(PurchaseItem, Purchase, Store, StoreChain)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .join(Store, Store.id == Purchase.store_id)
        .join(StoreChain, StoreChain.id == Store.store_chain_id)
        .where(
            Purchase.user_id == user_id,
            PurchaseItem.product_id == product.id,
            Purchase.currency == currency,
            PurchaseItem.standard_unit_snapshot == product.standard_unit,
        )
        .order_by(Purchase.purchase_date.asc())
    )
    rows = (await session.execute(stmt)).all()

    grouped: dict[str, list[tuple[PurchaseItem, Purchase, Store, StoreChain]]] = {}
    meta: dict[str, tuple[str, str]] = {}

    for item, purchase, store, chain in rows:
        # Unknown/independent stores under fallback 'other' always group by individual store branch
        if group_by == "branch" or chain.is_fallback:
            key = f"branch:{store.id}"
            slug = f"store-{store.id}"
            label = store.display_name
        else:
            key = f"chain:{chain.id}"
            slug = chain.slug
            label = chain.canonical_name
        grouped.setdefault(key, []).append((item, purchase, store, chain))
        meta[key] = (slug, label)

    comparison_rows: list[StorePriceComparisonRow] = []
    for key, entries in grouped.items():
        slug, label = meta[key]
        latest_item, latest_purchase, _, _ = entries[-1]
        reg_std_list = [
            e[0].regular_standard_unit_price
            for e in entries
            if e[0].regular_standard_unit_price is not None
        ]
        avg_std = (
            quantize_unit_price(sum(reg_std_list, Decimal("0")) / Decimal(len(reg_std_list)))
            if reg_std_list
            else None
        )
        comparison_rows.append(
            StorePriceComparisonRow(
                group_key=key,
                group_slug=slug,
                display_name=label,
                observation_count=len(entries),
                latest_observed_at=latest_purchase.purchase_date,
                latest_regular_unit_price=latest_item.unit_price,
                latest_regular_standard_price=latest_item.regular_standard_unit_price,
                avg_regular_standard_price=avg_std,
                min_regular_standard_price=min(reg_std_list) if reg_std_list else None,
                max_regular_standard_price=max(reg_std_list) if reg_std_list else None,
            )
        )

    comparison_rows.sort(
        key=lambda r: (
            r.latest_regular_standard_price is None,
            r.latest_regular_standard_price or Decimal("0"),
        )
    )

    is_sufficient = len(comparison_rows) >= 2
    reason: str | None = None
    if len(comparison_rows) == 0:
        reason = f"No confirmed purchases found for this product in {currency}."
    elif len(comparison_rows) == 1:
        reason = "Observed in only one store so far; at least two stores are required to compare."

    cheapest = comparison_rows[0].display_name if is_sufficient else None

    return ProductStoreComparisonResponse(
        product_id=product.id,
        product_name=product.normalized_name,
        currency=currency,
        standard_unit=product.standard_unit,
        group_by=group_by,
        is_sufficient=is_sufficient,
        insufficiency_reason=reason,
        cheapest_regular_group=cheapest,
        stores=comparison_rows,
    )

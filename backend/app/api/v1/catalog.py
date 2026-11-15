"""API routes for Categories, Store Chains, Stores, Products, Aliases, and Price Comparison."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.config import SupportedCurrency
from app.db.session import get_db_session
from app.models.product import Product, ProductAlias
from app.repositories.base import BaseRepository
from app.schemas.catalog import (
    CategoryCreateRequest,
    CategoryResponse,
    CategoryTreeNode,
    CategoryUpdateRequest,
    ProductAliasResponse,
    ProductCreateRequest,
    ProductPriceHistoryResponse,
    ProductResponse,
    ProductStoreComparisonResponse,
    ProductUpdateRequest,
    StoreChainResponse,
    StoreCreateRequest,
    StoreResponse,
    StoreUpdateRequest,
)
from app.services.catalog_service import (
    archive_user_product,
    archive_user_store,
    build_category_tree,
    compare_product_store_prices,
    create_custom_category,
    create_user_product,
    create_user_store,
    deactivate_custom_category,
    get_product_price_history,
    get_user_store,
    list_product_aliases,
    list_store_chains,
    list_user_products,
    list_user_stores,
    list_visible_categories,
    set_alias_confirmation_status,
    update_custom_category,
    update_user_product,
    update_user_store,
)

router = APIRouter()


# --- Categories ---
@router.get("/categories", response_model=list[CategoryResponse], tags=["categories"])
async def get_categories(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[CategoryResponse]:
    cats = await list_visible_categories(session, user_id, include_inactive=include_inactive)
    return [CategoryResponse.model_validate(c) for c in cats]


@router.get("/categories/tree", response_model=list[CategoryTreeNode], tags=["categories"])
async def get_categories_tree(
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[CategoryTreeNode]:
    return await build_category_tree(session, user_id)


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["categories"],
)
async def post_category(
    payload: CategoryCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> CategoryResponse:
    cat = await create_custom_category(session, user_id, payload)
    return CategoryResponse.model_validate(cat)


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    tags=["categories"],
)
async def patch_category(
    category_id: uuid.UUID,
    payload: CategoryUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> CategoryResponse:
    cat = await update_custom_category(session, user_id, category_id, payload)
    return CategoryResponse.model_validate(cat)


@router.delete(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    tags=["categories"],
)
async def delete_category(
    category_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> CategoryResponse:
    cat = await deactivate_custom_category(session, user_id, category_id)
    return CategoryResponse.model_validate(cat)


# --- Store Chains & Stores ---
@router.get("/store-chains", response_model=list[StoreChainResponse], tags=["stores"])
async def get_store_chains(
    session: AsyncSession = Depends(get_db_session),
    _user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[StoreChainResponse]:
    chains = await list_store_chains(session)
    return [StoreChainResponse.model_validate(c) for c in chains]


@router.get("/stores", response_model=list[StoreResponse], tags=["stores"])
async def get_stores(
    include_inactive: bool = False,
    store_chain_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[StoreResponse]:
    return await list_user_stores(
        session,
        user_id,
        include_inactive=include_inactive,
        store_chain_id=store_chain_id,
    )


@router.post(
    "/stores",
    response_model=StoreResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["stores"],
)
async def post_store(
    payload: StoreCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> StoreResponse:
    return await create_user_store(session, user_id, payload)


@router.get("/stores/{store_id}", response_model=StoreResponse, tags=["stores"])
async def get_store(
    store_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> StoreResponse:
    return await get_user_store(session, user_id, store_id)


@router.patch("/stores/{store_id}", response_model=StoreResponse, tags=["stores"])
async def patch_store(
    store_id: uuid.UUID,
    payload: StoreUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> StoreResponse:
    return await update_user_store(session, user_id, store_id, payload)


@router.delete("/stores/{store_id}", response_model=StoreResponse, tags=["stores"])
async def delete_store(
    store_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> StoreResponse:
    return await archive_user_store(session, user_id, store_id)


# --- Products ---
@router.get("/products", response_model=list[ProductResponse], tags=["products"])
async def get_products(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    product_type: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    purchased_from: datetime | None = None,
    purchased_to: datetime | None = None,
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ProductResponse]:
    prods = await list_user_products(
        session,
        user_id,
        q=q,
        category_id=category_id,
        store_id=store_id,
        product_type=product_type,
        min_price=min_price,
        max_price=max_price,
        purchased_from=purchased_from,
        purchased_to=purchased_to,
        include_inactive=include_inactive,
    )
    return [ProductResponse.model_validate(p) for p in prods]


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["products"],
)
async def post_product(
    payload: ProductCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductResponse:
    prod = await create_user_product(session, user_id, payload)
    return ProductResponse.model_validate(prod)


@router.get("/products/{product_id}", response_model=ProductResponse, tags=["products"])
async def get_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductResponse:
    repo = BaseRepository(session, user_id, Product)
    prod = await repo.get_by_id_or_raise(product_id)
    return ProductResponse.model_validate(prod)


@router.patch("/products/{product_id}", response_model=ProductResponse, tags=["products"])
async def patch_product(
    product_id: uuid.UUID,
    payload: ProductUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductResponse:
    prod = await update_user_product(session, user_id, product_id, payload)
    return ProductResponse.model_validate(prod)


@router.delete("/products/{product_id}", response_model=ProductResponse, tags=["products"])
async def delete_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductResponse:
    prod = await archive_user_product(session, user_id, product_id)
    return ProductResponse.model_validate(prod)


@router.get(
    "/products/{product_id}/price-history",
    response_model=ProductPriceHistoryResponse,
    tags=["products"],
)
async def get_price_history(
    product_id: uuid.UUID,
    currency: SupportedCurrency = Query(default="RON"),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductPriceHistoryResponse:
    return await get_product_price_history(session, user_id, product_id, currency=currency)


@router.get(
    "/products/{product_id}/store-comparison",
    response_model=ProductStoreComparisonResponse,
    tags=["products"],
)
async def get_store_comparison(
    product_id: uuid.UUID,
    currency: SupportedCurrency = Query(default="RON"),
    group_by: Literal["chain", "branch"] = Query(default="chain"),
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductStoreComparisonResponse:
    return await compare_product_store_prices(
        session,
        user_id,
        product_id,
        currency=currency,
        group_by=group_by,
    )


# --- Product Aliases ---
@router.get(
    "/product-aliases",
    response_model=list[ProductAliasResponse],
    tags=["product-aliases"],
)
async def get_aliases(
    confirmation_status: str | None = None,
    store_chain_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ProductAliasResponse]:
    aliases = await list_product_aliases(
        session,
        user_id,
        confirmation_status=confirmation_status,
        store_chain_id=store_chain_id,
        product_id=product_id,
    )
    return [ProductAliasResponse.model_validate(a) for a in aliases]


@router.get(
    "/product-aliases/{alias_id}",
    response_model=ProductAliasResponse,
    tags=["product-aliases"],
)
async def get_alias(
    alias_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductAliasResponse:
    repo = BaseRepository(session, user_id, ProductAlias)
    alias = await repo.get_by_id_or_raise(alias_id)
    return ProductAliasResponse.model_validate(alias)


@router.post(
    "/product-aliases/{alias_id}/confirm",
    response_model=ProductAliasResponse,
    tags=["product-aliases"],
)
async def post_confirm_alias(
    alias_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductAliasResponse:
    alias = await set_alias_confirmation_status(session, user_id, alias_id, "user_confirmed")
    return ProductAliasResponse.model_validate(alias)


@router.post(
    "/product-aliases/{alias_id}/reject",
    response_model=ProductAliasResponse,
    tags=["product-aliases"],
)
async def post_reject_alias(
    alias_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ProductAliasResponse:
    alias = await set_alias_confirmation_status(session, user_id, alias_id, "rejected")
    return ProductAliasResponse.model_validate(alias)

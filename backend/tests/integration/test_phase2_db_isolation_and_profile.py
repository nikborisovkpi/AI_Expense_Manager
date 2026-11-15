"""Phase 2 TDD tests: DB seeds, profile bootstrap, BaseRepository isolation, and Profile API."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError
from app.db.seed import seed_reference_data
from app.main import create_app
from app.models.agent import AgentAction, Conversation
from app.models.budget import Budget
from app.models.category import Category
from app.models.product import Product
from app.models.profile import AppInstallation, Profile
from app.models.purchase import Purchase
from app.models.receipt import Receipt
from app.models.shopping_list import ShoppingList
from app.models.store import Store, StoreChain
from app.repositories.base import BaseRepository
from app.services.profile_service import bootstrap_local_profile
from app.services.storage_service import InMemoryPrivateStorage


async def test_seed_creates_6_root_categories_and_store_chains_idempotently(
    db_session: AsyncSession,
) -> None:
    await seed_reference_data(db_session)
    await seed_reference_data(db_session)  # Idempotency check

    roots = (
        await db_session.scalars(
            select(Category).where(Category.parent_id.is_(None), Category.is_system.is_(True))
        )
    ).all()
    assert len(roots) == 6
    food_roots = [c for c in roots if c.macro_group == "food"]
    household_roots = [c for c in roots if c.macro_group == "household"]
    assert len(food_roots) == 1
    assert food_roots[0].slug == "food-and-beverages"
    assert len(household_roots) == 5

    subcategories = (
        await db_session.scalars(
            select(Category).where(Category.parent_id.is_not(None), Category.is_system.is_(True))
        )
    ).all()
    assert len(subcategories) >= 50

    chains = (await db_session.scalars(select(StoreChain))).all()
    chain_slugs = {c.slug for c in chains}
    assert {"lidl", "kaufland", "carrefour", "auchan", "penny", "atb", "silpo", "other"}.issubset(
        chain_slugs
    )
    fallback_chains = [c for c in chains if c.is_fallback]
    assert len(fallback_chains) == 1
    assert fallback_chains[0].slug == "other"


async def test_local_profile_bootstrap_is_idempotent_and_auto_detects_timezone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    p1, p2 = await asyncio.gather(
        bootstrap_local_profile(session_factory),
        bootstrap_local_profile(session_factory),
    )
    assert p1.id == p2.id
    assert p1.preferred_currency == "RON"
    assert ZoneInfo(p1.timezone).key == p1.timezone

    async with session_factory() as session:
        installations = (await session.scalars(select(AppInstallation))).all()
        assert len(installations) == 1
        assert installations[0].active_profile_id == p1.id


async def test_base_repository_strict_cross_user_isolation(
    db_session: AsyncSession,
) -> None:
    await seed_reference_data(db_session)
    chain = (await db_session.scalars(select(StoreChain).where(StoreChain.slug == "lidl"))).one()
    category = (
        await db_session.scalars(select(Category).where(Category.slug == "dairy-products"))
    ).one()

    user_a = Profile(display_name="User A", preferred_currency="RON", locale="en", timezone="UTC")
    user_b = Profile(display_name="User B", preferred_currency="RON", locale="en", timezone="UTC")
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    # Create user_a entities through BaseRepository
    store_repo_a = BaseRepository(db_session, user_a.id, Store)
    store_a = await store_repo_a.create(
        store_chain_id=chain.id,
        display_name="Lidl Pipera",
        city="Bucharest",
        country="RO",
    )

    cat_repo_a = BaseRepository(db_session, user_a.id, Category)
    custom_cat_a = await cat_repo_a.create(
        name="Pet Supplies",
        slug="pet-supplies",
        is_system=False,
        macro_group="household",
    )

    prod_repo_a = BaseRepository(db_session, user_a.id, Product)
    prod_a = await prod_repo_a.create(
        category_id=category.id,
        normalized_name="Milk 1.5L",
        product_type="consumable",
        package_size=Decimal("1.500"),
        package_unit="l",
        standard_unit="l",
        standard_quantity=Decimal("1.500000"),
    )

    purch_repo_a = BaseRepository(db_session, user_a.id, Purchase)
    purch_a = await purch_repo_a.create(
        store_id=store_a.id,
        title="Weekly Groceries",
        subtotal=Decimal("50.00"),
        amount=Decimal("50.00"),
        currency="RON",
        purchase_date=datetime.now(UTC),
        source="manual",
    )

    rec_repo_a = BaseRepository(db_session, user_a.id, Receipt)
    rec_a = await rec_repo_a.create(
        storage_path="receipts/a/1.jpg",
        file_type="image/jpeg",
        file_hash="abc123hash",
        status="queued",
    )

    bud_repo_a = BaseRepository(db_session, user_a.id, Budget)
    bud_a = await bud_repo_a.create(
        amount=Decimal("1500.00"),
        currency="RON",
        period="monthly",
        start_date=date(2026, 11, 1),
    )

    list_repo_a = BaseRepository(db_session, user_a.id, ShoppingList)
    list_a = await list_repo_a.create(name="Weekend List", currency="RON", status="active")

    conv_repo_a = BaseRepository(db_session, user_a.id, Conversation)
    conv_a = await conv_repo_a.create(title="My Expenses Chat")

    act_repo_a = BaseRepository(db_session, user_a.id, AgentAction)
    act_a = await act_repo_a.create(
        action_type="create_budget",
        arguments={"amount": "500.00"},
        arguments_hash="hash1",
        status="pending",
        expires_at=datetime.now(UTC),
    )
    await db_session.commit()

    # Verify user_b cannot read, update, or delete ANY of user_a's records
    model_and_records = [
        (Store, store_a.id, {"display_name": "Hacked"}),
        (Category, custom_cat_a.id, {"name": "Hacked"}),
        (Product, prod_a.id, {"normalized_name": "Hacked"}),
        (Purchase, purch_a.id, {"title": "Hacked"}),
        (Receipt, rec_a.id, {"status": "cancelled"}),
        (Budget, bud_a.id, {"amount": Decimal("1.00")}),
        (ShoppingList, list_a.id, {"name": "Hacked"}),
        (Conversation, conv_a.id, {"title": "Hacked"}),
        (AgentAction, act_a.id, {"status": "approved"}),
    ]

    for model_cls, record_id, update_payload in model_and_records:
        repo_b = BaseRepository(db_session, user_b.id, model_cls)  # type: ignore[type-var]
        assert await repo_b.get_by_id(record_id) is None
        assert await repo_b.list_all() == []
        with pytest.raises(NotFoundError):
            await repo_b.get_by_id_or_raise(record_id)
        with pytest.raises(NotFoundError):
            await repo_b.update(record_id, **update_payload)
        with pytest.raises(NotFoundError):
            await repo_b.delete(record_id)

    # Verify ownership check rejects cross-user linking
    repo_b_purchase = BaseRepository(db_session, user_b.id, Purchase)
    with pytest.raises(ForbiddenError):
        await repo_b_purchase.verify_owned_reference(Store, store_a.id)


async def test_profile_endpoints_and_private_avatar_proxy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="test")
    storage = InMemoryPrivateStorage()
    app = create_app(settings=settings, session_factory=session_factory, storage_service=storage)

    # Bootstrapping via lifespan-equivalent helper
    await bootstrap_local_profile(session_factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. GET /profile
        res = await client.get("/api/v1/profile")
        assert res.status_code == 200
        profile_data = res.json()
        assert profile_data["preferred_currency"] == "RON"
        assert profile_data["has_avatar"] is False
        assert profile_data["preferences"]["budget_alert_threshold_pct"] == 80

        # 2. PATCH /profile (ignoring any untrusted user_id in body)
        patch_res = await client.patch(
            "/api/v1/profile",
            json={
                "display_name": "Nikita",
                "preferred_currency": "UAH",
                "timezone": "Europe/Kyiv",
                "preferences": {
                    "budget_alert_threshold_pct": 85,
                    "budget_alerts_enabled": True,
                    "auto_refresh_insights": False,
                },
            },
        )
        assert patch_res.status_code == 200
        updated = patch_res.json()
        assert updated["id"] == profile_data["id"]
        assert updated["display_name"] == "Nikita"
        assert updated["preferred_currency"] == "UAH"
        assert updated["timezone"] == "Europe/Kyiv"
        assert updated["preferences"]["budget_alert_threshold_pct"] == 85

        # 3. Reject invalid avatar MIME type
        bad_upload = await client.post(
            "/api/v1/profile/avatar",
            files={"file": ("hack.exe", b"MZ...", "application/octet-stream")},
        )
        assert bad_upload.status_code == 400

        # 4. Upload valid PNG avatar
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        good_upload = await client.post(
            "/api/v1/profile/avatar",
            files={"file": ("avatar.png", png_bytes, "image/png")},
        )
        assert good_upload.status_code == 200
        assert good_upload.json()["has_avatar"] is True

        # 5. Stream private avatar through backend proxy
        avatar_get = await client.get("/api/v1/profile/avatar")
        assert avatar_get.status_code == 200
        assert avatar_get.content == png_bytes
        assert avatar_get.headers["content-type"] == "image/png"
        assert "private" in avatar_get.headers["cache-control"]

        # 6. Delete avatar
        del_res = await client.delete("/api/v1/profile/avatar")
        assert del_res.status_code == 200
        assert del_res.json()["has_avatar"] is False

        missing_avatar = await client.get("/api/v1/profile/avatar")
        assert missing_avatar.status_code == 404

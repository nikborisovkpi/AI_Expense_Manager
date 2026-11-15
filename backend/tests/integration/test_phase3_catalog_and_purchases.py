"""Phase 3 TDD integration tests: Catalog, Purchases, Snapshots, and Store Comparison."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.seed import seed_reference_data
from app.main import create_app
from app.models.receipt import Receipt
from app.services.profile_service import bootstrap_local_profile


async def test_catalog_purchases_snapshots_and_dual_price_comparison(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="test")
    app = create_app(settings=settings, session_factory=session_factory)

    async with session_factory() as session:
        await seed_reference_data(session)
    profile = await bootstrap_local_profile(session_factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Categories: tree + system protection + max 2-level custom categories
        tree_res = await client.get("/api/v1/categories/tree")
        assert tree_res.status_code == 200
        roots = tree_res.json()
        assert len(roots) == 6
        food_root = next(r for r in roots if r["slug"] == "food-and-beverages")
        dairy_sub = next(c for c in food_root["children"] if c["slug"] == "dairy-products")

        # Cannot modify or delete system category
        sys_del = await client.delete(f"/api/v1/categories/{dairy_sub['id']}")
        assert sys_del.status_code == 403

        # Cannot create 3rd-level category under a subcategory
        lvl3_res = await client.post(
            "/api/v1/categories",
            json={"name": "Organic Milk", "parent_id": dairy_sub["id"]},
        )
        assert lvl3_res.status_code == 422

        # Create valid custom subcategory under Food & Beverages
        custom_cat_res = await client.post(
            "/api/v1/categories",
            json={"name": "Specialty Cheese", "parent_id": food_root["id"]},
        )
        assert custom_cat_res.status_code == 201
        custom_cat = custom_cat_res.json()
        assert custom_cat["macro_group"] == "food"
        assert custom_cat["is_system"] is False

        # 2. Store chains & Stores (including unknown store fallback + rename)
        chains_res = await client.get("/api/v1/store-chains")
        assert chains_res.status_code == 200
        chains = chains_res.json()
        lidl_chain = next(c for c in chains if c["slug"] == "lidl")
        kaufland_chain = next(c for c in chains if c["slug"] == "kaufland")

        lidl_store = (
            await client.post(
                "/api/v1/stores",
                json={
                    "store_chain_id": lidl_chain["id"],
                    "display_name": "Lidl Militari",
                    "city": "Bucharest",
                    "country": "RO",
                },
            )
        ).json()
        kaufland_store = (
            await client.post(
                "/api/v1/stores",
                json={
                    "store_chain_id": kaufland_chain["id"],
                    "display_name": "Kaufland Barbu Vacarescu",
                    "city": "Bucharest",
                    "country": "RO",
                },
            )
        ).json()

        # Unknown store without store_chain_id automatically links to 'other' chain & saves name
        unknown_store_res = await client.post(
            "/api/v1/stores",
            json={"display_name": "Magazinul De La Colt"},
        )
        assert unknown_store_res.status_code == 201
        unknown_store = unknown_store_res.json()
        assert unknown_store["chain_slug"] == "other"
        assert unknown_store["display_name"] == "Magazinul De La Colt"

        # Rename unknown store
        renamed_store = (
            await client.patch(
                f"/api/v1/stores/{unknown_store['id']}",
                json={"display_name": "Băcănia Bunicii"},
            )
        ).json()
        assert renamed_store["display_name"] == "Băcănia Bunicii"

        # 3. Products & unit normalization (250g -> 0.25 kg)
        cheese_res = await client.post(
            "/api/v1/products",
            json={
                "category_id": custom_cat["id"],
                "normalized_name": "Telemea Maturata",
                "brand": "Hochland",
                "product_type": "consumable",
                "package_size": "250",
                "package_unit": "g",
            },
        )
        assert cheese_res.status_code == 201
        cheese = cheese_res.json()
        assert cheese["standard_unit"] == "kg"
        assert Decimal(cheese["standard_quantity"]) == Decimal("0.250000")

        # 4. Purchases at Lidl (regular 14.00 RON, promo -4.00 -> paid 10.00 RON)
        #    and Kaufland (regular 12.50 RON, no promo -> paid 12.50 RON)
        p_lidl_res = await client.post(
            "/api/v1/purchases",
            json={
                "store_id": lidl_store["id"],
                "title": "Lidl Shopping",
                "subtotal": "14.00",
                "discounts_total": "4.00",
                "amount": "10.00",
                "currency": "RON",
                "purchase_date": datetime(2026, 11, 10, 12, 0, tzinfo=UTC).isoformat(),
                "idempotency_key": "idem-lidl-1",
                "items": [
                    {
                        "product_id": cheese["id"],
                        "raw_name": "TELEMEA HOCHLAND 250G",
                        "quantity": "1",
                        "unit": "piece",
                        "unit_price": "14.00",
                        "discount_amount": "4.00",
                    }
                ],
            },
        )
        assert p_lidl_res.status_code == 201
        p_lidl = p_lidl_res.json()

        # Idempotent retry returns existing purchase without duplicating
        p_lidl_dup = await client.post(
            "/api/v1/purchases",
            json={
                "store_id": lidl_store["id"],
                "title": "Lidl Shopping",
                "subtotal": "14.00",
                "discounts_total": "4.00",
                "amount": "10.00",
                "currency": "RON",
                "purchase_date": datetime(2026, 11, 10, 12, 0, tzinfo=UTC).isoformat(),
                "idempotency_key": "idem-lidl-1",
                "items": [],
            },
        )
        assert p_lidl_dup.json()["id"] == p_lidl["id"]

        p_kauf_res = await client.post(
            "/api/v1/purchases",
            json={
                "store_id": kaufland_store["id"],
                "title": "Kaufland Shopping",
                "subtotal": "12.50",
                "discounts_total": "0.00",
                "amount": "12.50",
                "currency": "RON",
                "purchase_date": datetime(2026, 11, 12, 15, 0, tzinfo=UTC).isoformat(),
                "items": [
                    {
                        "product_id": cheese["id"],
                        "raw_name": "HOCHLAND TELEMEA 250G",
                        "quantity": "1",
                        "unit": "piece",
                        "unit_price": "12.50",
                        "discount_amount": "0.00",
                    }
                ],
            },
        )
        assert p_kauf_res.status_code == 201

        # 5. Store Comparison MUST compare ORIGINAL regular prices in RON/kg:
        #    Lidl regular = 14.00 / 0.25 = 56.00 RON/kg (even though promo paid was 40.00 RON/kg!)
        #    Kaufland regular = 12.50 / 0.25 = 50.00 RON/kg -> Kaufland has lower regular baseline!
        comp_res = await client.get(
            f"/api/v1/products/{cheese['id']}/store-comparison?currency=RON"
        )
        assert comp_res.status_code == 200
        comp = comp_res.json()
        assert comp["standard_unit"] == "kg"
        by_chain = {row["group_slug"]: row for row in comp["stores"]}
        assert Decimal(by_chain["lidl"]["latest_regular_standard_price"]) == Decimal("56.0000")
        assert Decimal(by_chain["kaufland"]["latest_regular_standard_price"]) == Decimal("50.0000")

        # 6. Historical snapshot immutability: rename custom category & archive product
        await client.patch(
            f"/api/v1/categories/{custom_cat['id']}",
            json={"name": "Renamed Cheese Category"},
        )
        del_prod = await client.delete(f"/api/v1/products/{cheese['id']}")
        assert del_prod.status_code == 200
        assert del_prod.json()["is_active"] is False

        items_res = await client.get(f"/api/v1/purchases/{p_lidl['id']}/items")
        assert items_res.status_code == 200
        saved_item = items_res.json()[0]
        # Snapshot kept original category name at purchase time!
        assert saved_item["category_name_snapshot"] == "Specialty Cheese"
        assert Decimal(saved_item["effective_total_price"]) == Decimal("10.00")

        # 7. Deleting purchase linked to receipt resets receipt to needs_review
        async with session_factory() as session:
            receipt = Receipt(
                user_id=profile.id,
                purchase_id=uuid.UUID(p_lidl["id"]),
                storage_path="receipts/test.jpg",
                file_type="image/jpeg",
                file_hash="hash-linked",
                status="confirmed",
            )
            session.add(receipt)
            await session.commit()
            receipt_id = receipt.id

        del_purchase = await client.delete(f"/api/v1/purchases/{p_lidl['id']}")
        assert del_purchase.status_code == 204

        async with session_factory() as session:
            updated_receipt = await session.scalar(select(Receipt).where(Receipt.id == receipt_id))
            assert updated_receipt is not None
            assert updated_receipt.purchase_id is None
            assert updated_receipt.status == "needs_review"

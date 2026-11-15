"""Phase 4 TDD tests: Timezone-aware Budgets, Multi-currency Analytics, and Cached Insights."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.seed import seed_reference_data
from app.main import create_app
from app.services.insight_service import refresh_stale_dashboard_insights
from app.services.profile_service import bootstrap_local_profile


async def test_timezone_budgets_currency_isolation_analytics_and_cached_insights(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="test")
    app = create_app(settings=settings, session_factory=session_factory)

    async with session_factory() as session:
        await seed_reference_data(session)
    await bootstrap_local_profile(session_factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Set profile timezone to Europe/Bucharest (UTC+2 in winter) and alert threshold 80%
        await client.patch(
            "/api/v1/profile",
            json={
                "timezone": "Europe/Bucharest",
                "preferred_currency": "RON",
                "preferences": {
                    "budget_alert_threshold_pct": 80,
                    "budget_alerts_enabled": True,
                    "auto_refresh_insights": True,
                },
            },
        )

        # Fetch categories & stores
        tree = (await client.get("/api/v1/categories/tree")).json()
        food_root = next(r for r in tree if r["slug"] == "food-and-beverages")
        dairy_sub = next(c for c in food_root["children"] if c["slug"] == "dairy-products")
        cleaning_root = next(r for r in tree if r["slug"] == "cleaning-products-and-accessories")
        laundry_sub = next(
            c for c in cleaning_root["children"] if c["slug"] == "laundry-detergents"
        )

        chains = (await client.get("/api/v1/store-chains")).json()
        lidl_chain = next(c for c in chains if c["slug"] == "lidl")
        lidl = (
            await client.post(
                "/api/v1/stores",
                json={"store_chain_id": lidl_chain["id"], "display_name": "Lidl Titan"},
            )
        ).json()

        milk = (
            await client.post(
                "/api/v1/products",
                json={
                    "category_id": dairy_sub["id"],
                    "normalized_name": "Milk 3.5%",
                    "brand": "Pilos",
                    "package_size": "1",
                    "package_unit": "l",
                },
            )
        ).json()
        detergent = (
            await client.post(
                "/api/v1/products",
                json={
                    "category_id": laundry_sub["id"],
                    "normalized_name": "Liquid Detergent",
                    "brand": "Formil",
                    "package_size": "2",
                    "package_unit": "l",
                },
            )
        ).json()

        # Purchase 1: 2026-10-31 22:30 UTC == 2026-11-01 00:30 Europe/Bucharest (NOVEMBER!)
        # Milk 6.00x10=60.00 + Detergent 40.00x1=40.00, basket discount -10.00 -> 90.00 RON
        await client.post(
            "/api/v1/purchases",
            json={
                "store_id": lidl["id"],
                "title": "Late Night Shopping",
                "subtotal": "100.00",
                "discounts_total": "10.00",
                "amount": "90.00",
                "currency": "RON",
                "purchase_date": datetime(2026, 10, 31, 22, 30, tzinfo=UTC).isoformat(),
                "items": [
                    {
                        "product_id": milk["id"],
                        "raw_name": "LAPTE PILOS 1L",
                        "quantity": "10",
                        "unit": "piece",
                        "unit_price": "6.00",
                    },
                    {
                        "product_id": detergent["id"],
                        "raw_name": "DETERGENT FORMIL 2L",
                        "quantity": "1",
                        "unit": "piece",
                        "unit_price": "40.00",
                    },
                ],
            },
        )

        # Purchase 2: 2026-11-10 12:00 UTC — Milk price rose from 6.00 -> 7.20 RON (+20%)
        await client.post(
            "/api/v1/purchases",
            json={
                "store_id": lidl["id"],
                "title": "Mid-month Milk",
                "subtotal": "7.20",
                "amount": "7.20",
                "currency": "RON",
                "purchase_date": datetime(2026, 11, 10, 12, 0, tzinfo=UTC).isoformat(),
                "items": [
                    {
                        "product_id": milk["id"],
                        "raw_name": "LAPTE PILOS 1L",
                        "quantity": "1",
                        "unit": "piece",
                        "unit_price": "7.20",
                    }
                ],
            },
        )

        # Purchase 3: EUR purchase (50.00 EUR) — MUST NOT contaminate RON budgets or RON totals
        await client.post(
            "/api/v1/purchases",
            json={
                "store_id": lidl["id"],
                "title": "Duty Free EUR",
                "subtotal": "50.00",
                "amount": "50.00",
                "currency": "EUR",
                "purchase_date": datetime(2026, 11, 12, 10, 0, tzinfo=UTC).isoformat(),
                "items": [
                    {
                        "category_id": dairy_sub["id"],
                        "raw_name": "CHEESE EUR",
                        "quantity": "1",
                        "unit": "piece",
                        "unit_price": "50.00",
                    }
                ],
            },
        )

        # Create Overall RON budget (110.00 RON -> 97.20 spent = 88.36% -> ALERT triggered!)
        b_overall = await client.post(
            "/api/v1/budgets",
            json={
                "name": "November Groceries",
                "amount": "110.00",
                "currency": "RON",
                "period": "monthly",
                "start_date": date(2026, 11, 1).isoformat(),
            },
        )
        assert b_overall.status_code == 201

        # Create Food budget (70.00 RON -> Milk spend: 54.00 + 7.20 = 61.20 RON = 87.43% -> ALERT!)
        b_food = await client.post(
            "/api/v1/budgets",
            json={
                "name": "Food Budget",
                "category_id": food_root["id"],
                "amount": "70.00",
                "currency": "RON",
                "period": "monthly",
                "start_date": date(2026, 11, 1).isoformat(),
            },
        )
        assert b_food.status_code == 201

        status_res = await client.get("/api/v1/budgets/status?reference_date=2026-11-15")
        assert status_res.status_code == 200
        statuses = status_res.json()
        assert len(statuses) == 2

        overall_st = next(s for s in statuses if s["category_id"] is None)
        assert Decimal(overall_st["spent"]) == Decimal("97.20")
        assert Decimal(overall_st["remaining"]) == Decimal("12.80")
        assert overall_st["is_alert"] is True
        assert overall_st["is_exceeded"] is False

        food_st = next(s for s in statuses if s["category_id"] == food_root["id"])
        assert Decimal(food_st["spent"]) == Decimal("61.20")
        assert food_st["is_alert"] is True

        # Verify Analytics Summary groups strictly by currency and splits Food vs Household
        sum_res = await client.get("/api/v1/analytics/summary")
        assert sum_res.status_code == 200
        by_curr = {row["currency"]: row for row in sum_res.json()}
        assert set(by_curr.keys()) == {"RON", "EUR"}
        assert Decimal(by_curr["RON"]["total_spending"]) == Decimal("97.20")
        assert Decimal(by_curr["RON"]["food_spending"]) == Decimal("61.20")
        assert Decimal(by_curr["RON"]["household_spending"]) == Decimal("36.00")
        assert Decimal(by_curr["EUR"]["total_spending"]) == Decimal("50.00")

        # Verify Household-Spending endpoint
        hh_res = await client.get("/api/v1/analytics/household-spending?currency=RON")
        assert hh_res.status_code == 200
        hh_data = hh_res.json()
        assert Decimal(hh_data["total_household_spending"]) == Decimal("36.00")
        assert len(hh_data["categories"]) == 1

        # Verify Trends in Bucharest timezone puts 2026-10-31T22:30Z into 2026-11!
        trends_res = await client.get(
            "/api/v1/analytics/trends?currency=RON&months=3&reference_date=2026-11-15"
        )
        assert trends_res.status_code == 200
        nov_point = next(p for p in trends_res.json() if p["month"] == "2026-11")
        assert Decimal(nov_point["total_spending"]) == Decimal("97.20")

        # Verify Price Changes detects +20.00% on Milk (6.00 -> 7.20 RON/l)
        pc_res = await client.get("/api/v1/analytics/price-changes?currency=RON")
        assert pc_res.status_code == 200
        pc_items = pc_res.json()
        assert len(pc_items) == 1
        assert pc_items[0]["product_id"] == milk["id"]
        assert Decimal(pc_items[0]["pct_change"]) == Decimal("20.00")

        # Verify Cached Dashboard Insights (0 LLM calls on GET; refreshed via worker helper)
        ins_before = await client.get("/api/v1/dashboard/insights?currency=RON")
        assert ins_before.status_code == 200
        assert ins_before.json()["status"] == "stale"

        await refresh_stale_dashboard_insights(session_factory)

        ins_after = await client.get("/api/v1/dashboard/insights?currency=RON")
        assert ins_after.status_code == 200
        ins_body = ins_after.json()
        assert ins_body["status"] == "ready"
        assert len(ins_body["source_purchase_ids"]) == 2
        assert "highlights" in ins_body["content"]

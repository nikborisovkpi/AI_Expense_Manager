"""Phase 6 integration tests: Draft edit, unknown store confirm, and alias reuse."""

from __future__ import annotations

from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.receipt.schemas import ExtractedLineItem, ExtractedReceiptPayload
from app.core.config import Settings
from app.db.seed import seed_reference_data
from app.main import create_app
from app.services.profile_service import bootstrap_local_profile
from app.services.storage_service import InMemoryPrivateStorage
from app.workers.receipt_worker import process_single_queued_receipt


class UnknownStoreExtractor:
    def __init__(self, store_name: str, total: Decimal, receipt_no: str) -> None:
        self._store_name = store_name
        self._total = total
        self._receipt_no = receipt_no

    async def extract_receipt(
        self,
        _images: list[bytes],
    ) -> tuple[ExtractedReceiptPayload, dict[str, object], str, str]:
        payload = ExtractedReceiptPayload(
            store_name=self._store_name,
            receipt_number=self._receipt_no,
            purchase_date="2026-11-15T11:15:00+02:00",
            currency="RON",
            subtotal=Decimal("20.00"),
            discounts_total=Decimal("3.00"),
            container_deposit_total=Decimal("0.00"),
            total=self._total,
            items=[
                ExtractedLineItem(
                    raw_name="CAFEA BOABE JACOBS 500G",
                    normalized_name="Coffee Beans",
                    brand="Jacobs",
                    category_slug="coffee-and-tea",
                    quantity=Decimal("1"),
                    unit="piece",
                    package_size=Decimal("500"),
                    package_unit="g",
                    unit_price=Decimal("20.00"),
                    discount_amount=Decimal("3.00"),
                    total_price=Decimal("17.00"),
                    confidence=0.98,
                )
            ],
        )
        return payload, {"ok": True}, "anthropic/claude-sonnet-4.6", "receipt_v1"


async def test_unknown_store_receipt_draft_edit_idempotent_confirm_and_alias_reuse(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="test")
    storage = InMemoryPrivateStorage()
    app = create_app(settings=settings, session_factory=session_factory, storage_service=storage)

    async with session_factory() as session:
        await seed_reference_data(session)
    await bootstrap_local_profile(session_factory)

    img1 = b"\x89PNG\r\n\x1a\nreceipt-unknown-1"
    img2 = b"\x89PNG\r\n\x1a\nreceipt-unknown-2"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Upload receipt from unknown local supermarket with total mismatch (19.00 vs 17.00)
        r1 = (
            await client.post(
                "/api/v1/receipts/upload",
                files={"file": ("bon1.png", img1, "image/png")},
            )
        ).json()

        await process_single_queued_receipt(
            session_factory=session_factory,
            storage=storage,
            settings=settings,
            extractor=UnknownStoreExtractor("Supermarket La Bunica", Decimal("19.00"), "B-001"),
        )

        res1 = (await client.get(f"/api/v1/receipts/{r1['id']}/result")).json()
        assert res1["status"] == "needs_review"
        assert res1["editable_draft"]["store_chain_slug"] == "other"
        assert res1["editable_draft"]["store_name"] == "Supermarket La Bunica"
        assert len(res1["validation_warnings"]) >= 1

        # 2. User edits draft (fixes total to 17.00 RON) -> status 'extracted' with 0 warnings
        edited_draft = res1["editable_draft"]
        edited_draft["total"] = "17.00"
        patched = await client.patch(
            f"/api/v1/receipts/{r1['id']}/draft",
            json=edited_draft,
        )
        assert patched.status_code == 200
        assert patched.json()["validation_warnings"] == []
        assert patched.json()["status"] == "extracted"

        # 3. Confirm receipt idempotently
        conf1 = await client.post(
            f"/api/v1/receipts/{r1['id']}/confirm",
            json={"idempotency_key": "confirm-r1-key"},
        )
        assert conf1.status_code == 201
        purchase1 = conf1.json()
        assert purchase1["source"] == "receipt"
        assert purchase1["store_display_name"] == "Supermarket La Bunica"
        assert Decimal(purchase1["amount"]) == Decimal("17.00")

        # Duplicate confirm retry with same idempotency_key returns same purchase
        conf1_retry = await client.post(
            f"/api/v1/receipts/{r1['id']}/confirm",
            json={"idempotency_key": "confirm-r1-key"},
        )
        assert conf1_retry.json()["id"] == purchase1["id"]

        # Verify dual pricing on confirmed 500g (0.5 kg) coffee:
        # Regular price = 20.00 / 0.5 kg = 40.0000 RON/kg; Paid = 17.00 / 0.5 kg = 34.0000 RON/kg
        coffee_item = purchase1["items"][0]
        assert coffee_item["standard_unit_snapshot"] == "kg"
        assert Decimal(coffee_item["regular_standard_unit_price"]) == Decimal("40.0000")
        assert Decimal(coffee_item["paid_standard_unit_price"]) == Decimal("34.0000")

        # 4. User can edit the saved unknown store's name
        store_id = purchase1["store_id"]
        rename_res = await client.patch(
            f"/api/v1/stores/{store_id}",
            json={"display_name": "Magazinul La Bunica (Edited)"},
        )
        assert rename_res.status_code == 200
        assert rename_res.json()["display_name"] == "Magazinul La Bunica (Edited)"

        # 5. Second receipt from same chain reuses confirmed ProductAlias automatically!
        r2 = (
            await client.post(
                "/api/v1/receipts/upload",
                files={"file": ("bon2.png", img2, "image/png")},
            )
        ).json()
        await process_single_queued_receipt(
            session_factory=session_factory,
            storage=storage,
            settings=settings,
            extractor=UnknownStoreExtractor(
                "Magazinul La Bunica (Edited)", Decimal("17.00"), "B-002"
            ),
        )
        res2 = (await client.get(f"/api/v1/receipts/{r2['id']}/result")).json()
        item2 = res2["editable_draft"]["items"][0]
        assert item2["matched_product_id"] == coffee_item["product_id"]
        assert item2["alias_confidence"] == "confirmed"

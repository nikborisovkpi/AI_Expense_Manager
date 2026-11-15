"""Phase 5 integration tests: Receipt upload, deduplication, watchdog, and worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.receipt.schemas import ExtractedLineItem, ExtractedReceiptPayload
from app.core.config import Settings
from app.db.seed import seed_reference_data
from app.main import create_app
from app.models.receipt import Receipt
from app.services.profile_service import bootstrap_local_profile
from app.services.storage_service import InMemoryPrivateStorage
from app.workers.receipt_worker import process_single_queued_receipt
from app.workers.watchdog import recover_expired_receipt_leases


class FakeReceiptVisionExtractor:
    async def extract_receipt(
        self,
        _images: list[bytes],
    ) -> tuple[ExtractedReceiptPayload, dict[str, object], str, str]:
        payload = ExtractedReceiptPayload(
            store_name="Lidl Romania",
            branch_name="Lidl Crangasi",
            store_cui="RO22891860",
            receipt_number="BF-00491",
            purchase_date="2026-11-14T14:30:00+02:00",
            currency="RON",
            subtotal=Decimal("13.00"),
            discounts_total=Decimal("2.00"),
            tax_total=Decimal("0.99"),
            container_deposit_total=Decimal("0.50"),
            rounding_adjustment=Decimal("0.00"),
            total=Decimal("11.50"),
            items=[
                ExtractedLineItem(
                    raw_name="LAPTE PILOS 3.5% 1L",
                    normalized_name="Milk 3.5%",
                    brand="Pilos",
                    category_slug="dairy-products",
                    quantity=Decimal("2"),
                    unit="piece",
                    package_size=Decimal("1"),
                    package_unit="l",
                    unit_price=Decimal("6.50"),
                    discount_amount=Decimal("2.00"),
                    total_price=Decimal("11.00"),
                    is_deposit_line=False,
                    confidence=0.95,
                )
            ],
        )
        return (
            payload,
            {"raw": "vision_json", "items_count": 1},
            "anthropic/claude-sonnet-4.6",
            "receipt_v1",
        )


async def test_receipt_upload_deduplication_watchdog_and_worker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="test", RECEIPT_MAX_ATTEMPTS=2)
    storage = InMemoryPrivateStorage()
    app = create_app(settings=settings, session_factory=session_factory, storage_service=storage)

    async with session_factory() as session:
        await seed_reference_data(session)
    profile = await bootstrap_local_profile(session_factory)

    jpg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Upload JPG receipt -> status='queued'
        up_res = await client.post(
            "/api/v1/receipts/upload",
            files={"file": ("lidl_bon.jpg", jpg_bytes, "image/jpeg")},
        )
        assert up_res.status_code == 201
        receipt_data = up_res.json()
        receipt_id = receipt_data["id"]
        assert receipt_data["status"] == "queued"

        # 2. Duplicate upload of same file_hash returns 409 Conflict with existing_receipt_id
        dup_res = await client.post(
            "/api/v1/receipts/upload",
            files={"file": ("lidl_bon_copy.jpg", jpg_bytes, "image/jpeg")},
        )
        assert dup_res.status_code == 409
        assert dup_res.json()["error"]["details"]["existing_receipt_id"] == receipt_id

        # 3. Private file proxy streams exact uploaded bytes
        file_res = await client.get(f"/api/v1/receipts/{receipt_id}/file")
        assert file_res.status_code == 200
        assert file_res.content == jpg_bytes

        # 4. Simulate stale crash mid-processing (Review Focus #3)
        import uuid

        rec_uuid = uuid.UUID(receipt_id)
        async with session_factory() as session:
            rec = await session.scalar(select(Receipt).where(Receipt.id == rec_uuid))
            assert rec is not None
            rec.status = "processing"
            rec.attempt_count = 1
            rec.processing_started_at = datetime.now(UTC) - timedelta(minutes=10)
            rec.processing_lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
            await session.commit()

        recovered = await recover_expired_receipt_leases(session_factory)
        assert recovered == 1

        st_res = await client.get(f"/api/v1/receipts/{receipt_id}/status")
        assert st_res.json()["status"] == "queued"

        # 5. Run worker step once with FakeReceiptVisionExtractor
        processed = await process_single_queued_receipt(
            session_factory=session_factory,
            storage=storage,
            settings=settings,
            extractor=FakeReceiptVisionExtractor(),
        )
        assert processed is True

        res_data = (await client.get(f"/api/v1/receipts/{receipt_id}/result")).json()
        assert res_data["status"] in ("extracted", "needs_review")
        assert res_data["model_name"] == "anthropic/claude-sonnet-4.6"
        assert res_data["editable_draft"]["store_chain_slug"] == "lidl"
        assert res_data["editable_draft"]["total"] == "11.50"
        assert len(res_data["editable_draft"]["items"]) == 1

        # 6. Upload a second receipt, cancel it, then delete it
        other_bytes = jpg_bytes + b"extra"
        up2 = (
            await client.post(
                "/api/v1/receipts/upload",
                files={"file": ("second.jpg", other_bytes, "image/jpeg")},
            )
        ).json()
        cancel_res = await client.post(f"/api/v1/receipts/{up2['id']}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"

        del_res = await client.delete(f"/api/v1/receipts/{up2['id']}")
        assert del_res.status_code == 204

        # 7. Verify watchdog marks exhausted lease as failed when attempt_count >= max_attempts
        async with session_factory() as session:
            exhausted = Receipt(
                user_id=profile.id,
                storage_path="receipts/exhausted.jpg",
                file_type="image/jpeg",
                file_hash="exhausted-hash",
                status="processing",
                attempt_count=2,
                max_attempts=2,
                processing_lease_expires_at=datetime.now(UTC) - timedelta(seconds=10),
            )
            session.add(exhausted)
            await session.commit()
            exhausted_id = exhausted.id

        await recover_expired_receipt_leases(session_factory)
        exhausted_status = (await client.get(f"/api/v1/receipts/{exhausted_id}/status")).json()
        assert exhausted_status["status"] == "failed"

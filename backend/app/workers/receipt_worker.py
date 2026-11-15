"""In-process async receipt worker using PostgreSQL row-lock leases (Section 7.1)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.receipt.extractor import (
    OpenRouterReceiptVisionExtractor,
    ReceiptVisionExtractor,
)
from app.ai.receipt.pdf_converter import render_pdf_bytes_to_png_pages
from app.ai.receipt.schemas import EditableReceiptDraft, ValidationWarning
from app.ai.receipt.validator import (
    compute_receipt_fingerprint,
    normalize_and_validate_extraction,
    normalize_receipt_label,
)
from app.core.config import Settings
from app.db.base import utcnow
from app.models.category import Category
from app.models.product import ProductAlias
from app.models.receipt import Receipt
from app.models.store import Store, StoreChain
from app.services.insight_service import refresh_stale_dashboard_insights
from app.services.storage_service import PrivateStorageService
from app.workers.watchdog import recover_expired_receipt_leases

logger = logging.getLogger(__name__)


async def _claim_next_queued_receipt(
    session_factory: async_sessionmaker[AsyncSession],
    lease_seconds: int,
) -> tuple[uuid.UUID, uuid.UUID, str, str] | None:
    """Atomically claim one queued receipt using SELECT ... FOR UPDATE SKIP LOCKED."""
    now = utcnow()
    async with session_factory() as session:
        stmt = (
            select(Receipt)
            .where(Receipt.status == "queued")
            .order_by(Receipt.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        receipt = await session.scalar(stmt)
        if receipt is None:
            return None

        receipt.status = "processing"
        receipt.attempt_count += 1
        receipt.processing_started_at = now
        receipt.processing_lease_expires_at = now + timedelta(seconds=lease_seconds)
        receipt.extraction_error = None
        claimed = (receipt.id, receipt.user_id, receipt.storage_path, receipt.file_type)
        await session.commit()
        return claimed


async def _enrich_draft_with_catalog(
    session: AsyncSession,
    user_id: uuid.UUID,
    draft: EditableReceiptDraft,
) -> tuple[EditableReceiptDraft, list[ValidationWarning]]:
    """Match store chain, user store, categories, and confirmed product_aliases."""
    extra_warnings: list[ValidationWarning] = []
    chains = list((await session.scalars(select(StoreChain))).all())
    fallback_chain = next(c for c in chains if c.is_fallback)

    matched_chain: StoreChain = fallback_chain
    norm_store = draft.store_name.strip().lower()
    for ch in chains:
        if ch.is_fallback:
            continue
        aliases = [str(a).lower() for a in (ch.aliases or [])]
        if ch.normalized_name in norm_store or any(a in norm_store for a in aliases):
            matched_chain = ch
            break

    draft.store_chain_id = matched_chain.id
    draft.store_chain_slug = matched_chain.slug

    # Match existing user Store branch if one exists
    user_stores = list(
        (
            await session.scalars(
                select(Store).where(
                    Store.user_id == user_id,
                    Store.store_chain_id == matched_chain.id,
                    Store.is_active.is_(True),
                )
            )
        ).all()
    )
    if matched_chain.is_fallback:
        for st in user_stores:
            if st.display_name.strip().lower() == norm_store:
                draft.store_id = st.id
                break
    elif len(user_stores) == 1:
        draft.store_id = user_stores[0].id

    # Category lookup (system + user custom)
    cats = list(
        (
            await session.scalars(
                select(Category).where(
                    Category.is_active.is_(True),
                    (Category.is_system.is_(True)) | (Category.user_id == user_id),
                )
            )
        ).all()
    )
    cats_by_slug = {c.slug: c for c in cats}

    # Confirmed product aliases for this chain
    confirmed_aliases = {
        a.normalized_raw_name: a.product_id
        for a in (
            await session.scalars(
                select(ProductAlias).where(
                    ProductAlias.user_id == user_id,
                    ProductAlias.store_chain_id == matched_chain.id,
                    ProductAlias.confirmation_status == "user_confirmed",
                )
            )
        ).all()
    }

    for idx, item in enumerate(draft.items):
        norm_label = normalize_receipt_label(item.raw_name)
        if norm_label in confirmed_aliases:
            item.matched_product_id = confirmed_aliases[norm_label]
            item.alias_confidence = "confirmed"

        if item.category_slug and item.category_slug in cats_by_slug:
            item.category_id = cats_by_slug[item.category_slug].id
        else:
            extra_warnings.append(
                ValidationWarning(
                    field=f"items[{idx}].category_id",
                    code="unclassified_category",
                    severity="warning",
                    message=f"Please select a category for '{item.raw_name}'.",
                )
            )

    return draft, extra_warnings


async def process_single_queued_receipt(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: PrivateStorageService,
    settings: Settings,
    extractor: ReceiptVisionExtractor | None = None,
) -> bool:
    claimed = await _claim_next_queued_receipt(
        session_factory,
        settings.receipt_processing_timeout_seconds,
    )
    if claimed is None:
        return False

    receipt_id, user_id, storage_path, file_type = claimed
    resolved_extractor = extractor or OpenRouterReceiptVisionExtractor(settings)

    try:
        raw_bytes, _ = await storage.download(
            bucket=settings.supabase_receipts_bucket,
            path=storage_path,
        )
        if file_type.lower() == "application/pdf":
            images = render_pdf_bytes_to_png_pages(raw_bytes)
        else:
            images = [raw_bytes]

        (
            extracted_payload,
            raw_response,
            model_used,
            prompt_ver,
        ) = await resolved_extractor.extract_receipt(images)
        draft, warnings = normalize_and_validate_extraction(extracted_payload)

        async with session_factory() as session:
            rec = await session.scalar(select(Receipt).where(Receipt.id == receipt_id))
            if rec is None or rec.status == "cancelled":
                return True

            draft, catalog_warnings = await _enrich_draft_with_catalog(session, user_id, draft)
            all_warnings = [*warnings, *catalog_warnings]

            fingerprint = compute_receipt_fingerprint(
                store_key=draft.store_chain_slug
                if draft.store_chain_slug != "other"
                else draft.store_name,
                purchase_date=draft.purchase_date,
                total=draft.total,
                receipt_number=draft.receipt_number,
            )
            if fingerprint:
                dup = await session.scalar(
                    select(Receipt).where(
                        Receipt.user_id == user_id,
                        Receipt.id != receipt_id,
                        Receipt.receipt_fingerprint == fingerprint,
                        Receipt.status.not_in(["cancelled", "failed"]),
                    )
                )
                if dup is not None:
                    all_warnings.append(
                        ValidationWarning(
                            field="receipt_number",
                            code="possible_duplicate_receipt",
                            severity="warning",
                            message=f"Possible duplicate of receipt {dup.id}.",
                        )
                    )

            rec.receipt_number = draft.receipt_number
            rec.store_cui = draft.store_cui
            rec.receipt_fingerprint = fingerprint
            rec.extracted_data = extracted_payload.model_dump(mode="json")
            rec.raw_model_response = raw_response
            rec.model_name = model_used
            rec.prompt_version = prompt_ver
            rec.editable_draft = draft.model_dump(mode="json")
            rec.validation_warnings = [w.model_dump(mode="json") for w in all_warnings]
            rec.processing_lease_expires_at = None
            rec.status = "needs_review" if all_warnings else "extracted"
            await session.commit()
        return True

    except Exception as exc:
        logger.warning("Receipt job %s failed: %s", receipt_id, type(exc).__name__)
        async with session_factory() as session:
            rec = await session.scalar(select(Receipt).where(Receipt.id == receipt_id))
            if rec is not None and rec.status != "cancelled":
                rec.processing_lease_expires_at = None
                if rec.attempt_count >= rec.max_attempts:
                    rec.status = "failed"
                    rec.extraction_error = "Receipt extraction failed after maximum retry attempts."
                else:
                    rec.status = "queued"
                    rec.extraction_error = "Temporary processing error; scheduled for retry."
                await session.commit()
        return True


async def run_background_worker_loop(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: PrivateStorageService,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Background asyncio worker loop inside the FastAPI web process."""
    last_watchdog = 0.0
    loop = asyncio.get_running_loop()

    while not stop_event.is_set():
        now_mono = loop.time()
        if now_mono - last_watchdog >= settings.receipt_watchdog_interval_seconds:
            try:
                await recover_expired_receipt_leases(session_factory)
                await refresh_stale_dashboard_insights(session_factory)
            except Exception:
                logger.exception("Periodic watchdog/insight pass encountered an error")
            last_watchdog = now_mono

        try:
            did_work = await process_single_queued_receipt(
                session_factory=session_factory,
                storage=storage,
                settings=settings,
            )
        except Exception:
            logger.exception("Receipt worker poll iteration failed")
            did_work = False

        if not did_work:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.receipt_worker_poll_interval_seconds,
                )
            except TimeoutError:
                pass

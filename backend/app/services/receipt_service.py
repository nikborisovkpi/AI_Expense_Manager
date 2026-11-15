"""Receipt lifecycle, draft editing, and idempotent confirmation service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.receipt.schemas import EditableReceiptDraft, ValidationWarning
from app.ai.receipt.validator import normalize_receipt_label, validate_editable_draft
from app.core.config import Settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError, ValidationDomainError
from app.db.base import utcnow
from app.models.category import Category
from app.models.product import Product, ProductAlias
from app.models.profile import Profile
from app.models.purchase import Purchase, PurchaseItem
from app.models.receipt import Receipt
from app.models.store import Store
from app.repositories.base import BaseRepository
from app.schemas.purchase import PurchaseResponse
from app.schemas.receipt import (
    ReceiptConfirmRequest,
    ReceiptResultResponse,
    ReceiptStatusResponse,
    ReceiptSummaryResponse,
)
from app.services.catalog_service import get_visible_category_or_raise, resolve_store_chain
from app.services.pricing_service import (
    ItemPriceInput,
    allocate_purchase_items_pricing,
    normalize_measurement,
    quantize_money,
)
from app.services.purchase_service import build_purchase_response, mark_dashboard_insights_stale
from app.services.storage_service import PrivateStorageService

ALLOWED_RECEIPT_MIME_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}


def _to_result_response(rec: Receipt) -> ReceiptResultResponse:
    draft = (
        EditableReceiptDraft.model_validate(rec.editable_draft)
        if rec.editable_draft is not None
        else None
    )
    warnings = [ValidationWarning.model_validate(w) for w in (rec.validation_warnings or [])]
    return ReceiptResultResponse(
        id=rec.id,
        status=rec.status,
        purchase_id=rec.purchase_id,
        model_name=rec.model_name,
        prompt_version=rec.prompt_version,
        extracted_data=rec.extracted_data,
        editable_draft=draft,
        validation_warnings=warnings,
        extraction_error=rec.extraction_error,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


async def upload_receipt(
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    storage: PrivateStorageService,
    settings: Settings,
    filename: str | None,
    content_type: str,
    data: bytes,
) -> ReceiptSummaryResponse:
    norm_mime = content_type.strip().lower()
    ext = ALLOWED_RECEIPT_MIME_TYPES.get(norm_mime)
    if ext is None:
        raise BadRequestError(
            "Unsupported receipt file format. Allowed: JPG, JPEG, PNG, PDF.",
            details={"content_type": content_type},
        )
    if not data or len(data) > settings.receipt_max_file_size_bytes:
        raise BadRequestError(
            "Receipt file is empty or exceeds maximum allowed size (15 MB).",
            details={"size_bytes": len(data)},
        )

    file_hash = hashlib.sha256(data).hexdigest()
    repo = BaseRepository(session, user_id, Receipt)
    existing = await repo.scalar_one_or_none(
        repo.scoped_select().where(
            Receipt.file_hash == file_hash,
            Receipt.status.not_in(["cancelled", "failed"]),
        )
    )
    if existing is not None:
        raise ConflictError(
            "This receipt file has already been uploaded.",
            details={"existing_receipt_id": str(existing.id), "status": existing.status},
        )

    receipt_id = uuid.uuid4()
    storage_path = f"{user_id}/{receipt_id}.{ext}"
    await storage.upload(
        bucket=settings.supabase_receipts_bucket,
        path=storage_path,
        data=data,
        content_type=norm_mime,
    )

    rec = await repo.create(
        id=receipt_id,
        storage_path=storage_path,
        original_filename=(filename or f"receipt.{ext}")[:255],
        file_type=norm_mime,
        file_size_bytes=len(data),
        file_hash=file_hash,
        status="queued",
        attempt_count=0,
        max_attempts=settings.receipt_max_attempts,
    )
    await session.commit()
    await session.refresh(rec)
    return ReceiptSummaryResponse.model_validate(rec)


async def list_receipts(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ReceiptSummaryResponse]:
    repo = BaseRepository(session, user_id, Receipt)
    stmt = repo.scoped_select()
    if status_filter is not None:
        stmt = stmt.where(Receipt.status == status_filter)
    stmt = stmt.order_by(Receipt.created_at.desc()).limit(limit).offset(offset)
    rows = await repo.list_matching(stmt)
    return [ReceiptSummaryResponse.model_validate(r) for r in rows]


async def get_receipt_status(
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
) -> ReceiptStatusResponse:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    return ReceiptStatusResponse(
        id=rec.id,
        status=rec.status,
        attempt_count=rec.attempt_count,
        max_attempts=rec.max_attempts,
        processing_started_at=rec.processing_started_at,
        processing_lease_expires_at=rec.processing_lease_expires_at,
        extraction_error=rec.extraction_error,
        purchase_id=rec.purchase_id,
        updated_at=rec.updated_at,
    )


async def get_receipt_result(
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
) -> ReceiptResultResponse:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    return _to_result_response(rec)


async def download_receipt_file(
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
    storage: PrivateStorageService,
    settings: Settings,
) -> tuple[bytes, str]:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    content, _ = await storage.download(
        bucket=settings.supabase_receipts_bucket,
        path=rec.storage_path,
    )
    return content, rec.file_type


async def retry_failed_receipt(
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
) -> ReceiptStatusResponse:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    if rec.status != "failed":
        raise ConflictError("Only failed receipts can be retried.")
    if rec.attempt_count >= rec.max_attempts:
        rec.max_attempts = rec.attempt_count + 1
    rec.status = "queued"
    rec.extraction_error = None
    rec.processing_lease_expires_at = None
    await session.commit()
    await session.refresh(rec)
    return await get_receipt_status(session, user_id, receipt_id)


async def cancel_receipt(
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
) -> ReceiptStatusResponse:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    if rec.status == "confirmed":
        raise ConflictError("Confirmed receipts cannot be cancelled.")
    rec.status = "cancelled"
    rec.processing_lease_expires_at = None
    await session.commit()
    await session.refresh(rec)
    return await get_receipt_status(session, user_id, receipt_id)


async def delete_receipt(
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
    storage: PrivateStorageService,
    settings: Settings,
) -> None:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    if rec.purchase_id is not None:
        raise ConflictError(
            "Cannot delete a confirmed receipt while its purchase exists. "
            "Delete the purchase first."
        )
    await storage.delete(bucket=settings.supabase_receipts_bucket, path=rec.storage_path)
    await repo.delete(receipt_id)
    await session.commit()


async def update_receipt_draft(
    session: AsyncSession,
    user_id: uuid.UUID,
    receipt_id: uuid.UUID,
    draft: EditableReceiptDraft,
) -> ReceiptResultResponse:
    repo = BaseRepository(session, user_id, Receipt)
    rec = await repo.get_by_id_or_raise(receipt_id)
    if rec.status == "confirmed":
        raise ConflictError("Confirmed receipts cannot have their review draft edited.")

    warnings = validate_editable_draft(draft)
    rec.editable_draft = draft.model_dump(mode="json")
    rec.validation_warnings = [w.model_dump(mode="json") for w in warnings]
    rec.status = "needs_review" if warnings else "extracted"
    await session.commit()
    await session.refresh(rec)
    return _to_result_response(rec)


def _parse_purchase_datetime(raw_date: str | None, profile_tz_name: str) -> datetime:
    if not raw_date:
        raise ValidationDomainError("Purchase date is required to confirm a receipt.")
    cleaned = raw_date.strip()
    tz = ZoneInfo(profile_tz_name)
    try:
        if len(cleaned) == 10:
            dt = datetime.fromisoformat(cleaned).replace(tzinfo=tz)
        else:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
    except ValueError as exc:
        raise ValidationDomainError(f"Invalid purchase_date format: {raw_date!r}") from exc
    return dt.astimezone(UTC)


async def confirm_receipt_to_purchase(
    session: AsyncSession,
    profile: Profile,
    receipt_id: uuid.UUID,
    payload: ReceiptConfirmRequest,
) -> PurchaseResponse:
    """Atomically and idempotently confirm a reviewed receipt into Purchase + PurchaseItems."""
    user_id = profile.id
    rec_repo = BaseRepository(session, user_id, Receipt)
    rec = await rec_repo.get_by_id_or_raise(receipt_id)

    # Idempotent return if already confirmed with same receipt or idempotency_key
    purch_repo = BaseRepository(session, user_id, Purchase)
    if rec.purchase_id is not None:
        existing_purchase = await purch_repo.get_by_id(rec.purchase_id)
        if existing_purchase is not None:
            if rec.idempotency_key == payload.idempotency_key:
                return await build_purchase_response(session, existing_purchase)
            raise ConflictError("Receipt has already been confirmed.")

    existing_by_key = await purch_repo.scalar_one_or_none(
        purch_repo.scoped_select().where(Purchase.idempotency_key == payload.idempotency_key)
    )
    if existing_by_key is not None:
        return await build_purchase_response(session, existing_by_key)

    draft = payload.draft
    if draft is None:
        if rec.editable_draft is None:
            raise ValidationDomainError("Receipt has no extracted draft to confirm.")
        draft = EditableReceiptDraft.model_validate(rec.editable_draft)

    if not draft.items:
        raise ValidationDomainError("Receipt must have at least one product item to confirm.")

    purchase_dt = _parse_purchase_datetime(draft.purchase_date, profile.timezone)

    # 1. Resolve or create Store (unknown stores automatically saved under fallback 'other' chain!)
    store_repo = BaseRepository(session, user_id, Store)
    store: Store
    if draft.store_id is not None:
        store = await store_repo.get_by_id_or_raise(draft.store_id)
    else:
        chain = await resolve_store_chain(session, draft.store_chain_id)
        existing_store = await store_repo.scalar_one_or_none(
            store_repo.scoped_select().where(
                Store.store_chain_id == chain.id,
                Store.display_name == draft.store_name.strip(),
                Store.is_active.is_(True),
            )
        )
        if existing_store is not None:
            store = existing_store
        else:
            store = await store_repo.create(
                store_chain_id=chain.id,
                display_name=draft.store_name.strip(),
                branch_name=draft.branch_name,
            )

    # Default fallback category ('other-food-products') if user left any item unclassified
    default_cat = await session.scalar(
        select(Category).where(Category.slug == "other-food-products", Category.is_system.is_(True))
    )

    # 2. Resolve/create Products, confirmed ProductAliases, and snapshot metadata
    prod_repo = BaseRepository(session, user_id, Product)
    alias_repo = BaseRepository(session, user_id, ProductAlias)
    item_specs: list[tuple[Product, Category | None]] = []
    price_inputs: list[ItemPriceInput] = []

    for item_draft in draft.items:
        cat: Category | None = None
        if item_draft.category_id is not None:
            cat = await get_visible_category_or_raise(session, user_id, item_draft.category_id)
        elif item_draft.category_slug:
            cat = await session.scalar(
                select(Category).where(
                    Category.slug == item_draft.category_slug,
                    (Category.is_system.is_(True)) | (Category.user_id == user_id),
                )
            )
        if cat is None:
            cat = default_cat
        if cat is None:
            raise NotFoundError("Default category missing; ensure seeds have run.")

        std_unit, std_qty = normalize_measurement(item_draft.package_size, item_draft.package_unit)

        prod: Product
        if item_draft.matched_product_id is not None:
            prod = await prod_repo.get_by_id_or_raise(item_draft.matched_product_id)
        else:
            existing_prod = await prod_repo.scalar_one_or_none(
                prod_repo.scoped_select().where(
                    Product.normalized_name == item_draft.normalized_name.strip(),
                    Product.package_size == item_draft.package_size,
                    Product.package_unit == item_draft.package_unit,
                    Product.is_active.is_(True),
                )
            )
            if existing_prod is not None:
                prod = existing_prod
            else:
                prod = await prod_repo.create(
                    category_id=cat.id,
                    normalized_name=item_draft.normalized_name.strip(),
                    brand=item_draft.brand.strip() if item_draft.brand else None,
                    product_type="consumable",
                    package_size=item_draft.package_size,
                    package_unit=item_draft.package_unit,
                    standard_unit=std_unit,
                    standard_quantity=std_qty,
                    is_active=True,
                )

        if item_draft.confirm_alias:
            norm_raw = normalize_receipt_label(item_draft.raw_name)
            existing_alias = await alias_repo.scalar_one_or_none(
                alias_repo.scoped_select().where(
                    ProductAlias.store_chain_id == store.store_chain_id,
                    ProductAlias.normalized_raw_name == norm_raw,
                )
            )
            if existing_alias is None:
                await alias_repo.create(
                    store_chain_id=store.store_chain_id,
                    product_id=prod.id,
                    raw_name=item_draft.raw_name.strip(),
                    normalized_raw_name=norm_raw,
                    confirmation_status="user_confirmed",
                    confirmed_by_user_at=utcnow(),
                )
            else:
                existing_alias.product_id = prod.id
                existing_alias.confirmation_status = "user_confirmed"
                existing_alias.confirmed_by_user_at = utcnow()

        item_specs.append((prod, cat))
        price_inputs.append(
            ItemPriceInput(
                quantity=item_draft.quantity,
                unit_price=item_draft.unit_price,
                discount_amount=item_draft.discount_amount,
                total_price=item_draft.total_price,
                standard_quantity=prod.standard_quantity,
            )
        )

    # 3. Create Purchase + dual-priced PurchaseItems
    purchase = await purch_repo.create(
        store_id=store.id,
        title=f"{store.display_name} Receipt",
        subtotal=quantize_money(draft.subtotal),
        discounts_total=quantize_money(draft.discounts_total),
        tax_total=quantize_money(draft.tax_total),
        tax_included=draft.tax_included,
        container_deposit_total=quantize_money(draft.container_deposit_total),
        rounding_adjustment=quantize_money(draft.rounding_adjustment),
        amount=quantize_money(draft.total),
        currency=draft.currency,
        purchase_date=purchase_dt,
        source="receipt",
        idempotency_key=payload.idempotency_key,
    )

    priced_results = allocate_purchase_items_pricing(
        items=price_inputs,
        final_amount=purchase.amount,
    )

    for item_draft, (prod, cat), calc in zip(draft.items, item_specs, priced_results, strict=True):
        session.add(
            PurchaseItem(
                purchase_id=purchase.id,
                product_id=prod.id,
                raw_name=item_draft.raw_name.strip(),
                quantity=item_draft.quantity,
                unit=item_draft.unit,
                unit_price=item_draft.unit_price,
                discount_amount=quantize_money(item_draft.discount_amount),
                total_price=calc.total_price,
                effective_total_price=calc.effective_total_price,
                category_id_snapshot=cat.id if cat else None,
                parent_category_id_snapshot=cat.parent_id if cat else None,
                category_name_snapshot=cat.name if cat else None,
                standard_unit_snapshot=prod.standard_unit,
                standard_quantity_snapshot=prod.standard_quantity,
                regular_standard_unit_price=calc.regular_standard_unit_price,
                paid_standard_unit_price=calc.paid_standard_unit_price,
            )
        )

    # 4. Link receipt one-way -> purchase and mark confirmed
    rec.purchase_id = purchase.id
    rec.status = "confirmed"
    rec.idempotency_key = payload.idempotency_key
    rec.editable_draft = draft.model_dump(mode="json")

    await mark_dashboard_insights_stale(session, user_id, purchase.currency)
    await session.commit()
    await session.refresh(purchase)
    return await build_purchase_response(session, purchase)

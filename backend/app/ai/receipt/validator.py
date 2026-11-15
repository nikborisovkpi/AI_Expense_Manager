"""Deterministic SGR deposit separation, arithmetic reconciliation, and receipt fingerprinting."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from app.ai.receipt.schemas import (
    EditableDraftItem,
    EditableReceiptDraft,
    ExtractedReceiptPayload,
    ValidationWarning,
)
from app.services.pricing_service import quantize_money

LINE_TOLERANCE = Decimal("0.02")
HEADER_TOLERANCE = Decimal("0.05")
LOW_CONFIDENCE_THRESHOLD = 0.75

SGR_PATTERNS = re.compile(r"\b(garantie\s*sgr|taxa\s*sgr|sgr\s*0[.,]50|deposit\s*sgr)\b", re.I)


def normalize_receipt_label(raw_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw_name.strip().lower())
    return cleaned[:255]


def compute_receipt_fingerprint(
    *,
    store_key: str,
    purchase_date: str | None,
    total: Decimal,
    receipt_number: str | None,
) -> str | None:
    if not purchase_date:
        return None
    canonical = "|".join(
        [
            store_key.strip().lower(),
            purchase_date.strip()[:16],
            f"{quantize_money(total):.2f}",
            (receipt_number or "").strip().lower(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_sgr_deposit_item(raw_name: str, flagged_by_model: bool) -> bool:
    if flagged_by_model:
        return True
    return bool(SGR_PATTERNS.search(raw_name))


def validate_editable_draft(draft: EditableReceiptDraft) -> list[ValidationWarning]:
    """Run deterministic arithmetic and completeness checks on an editable receipt draft."""
    warnings: list[ValidationWarning] = []

    if not draft.purchase_date:
        warnings.append(
            ValidationWarning(
                field="purchase_date",
                code="missing_purchase_date",
                severity="error",
                message="Purchase date could not be extracted; please enter it before confirming.",
            )
        )

    if not draft.items:
        warnings.append(
            ValidationWarning(
                field="items",
                code="empty_items",
                severity="error",
                message="No product items found on the receipt.",
            )
        )
        return warnings

    sum_item_totals = Decimal("0.00")
    sum_item_discounts = Decimal("0.00")

    for idx, item in enumerate(draft.items):
        expected_line = quantize_money(item.quantity * item.unit_price - item.discount_amount)
        if abs(expected_line - quantize_money(item.total_price)) > LINE_TOLERANCE:
            warnings.append(
                ValidationWarning(
                    field=f"items[{idx}].total_price",
                    code="item_total_mismatch",
                    severity="warning",
                    message=(
                        f"Item '{item.raw_name}': qty ({item.quantity}) * unit_price "
                        f"({item.unit_price}) - discount ({item.discount_amount}) = "
                        f"{expected_line}, which differs from line total {item.total_price}."
                    ),
                )
            )
        if item.confidence < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(
                ValidationWarning(
                    field=f"items[{idx}].raw_name",
                    code="low_extraction_confidence",
                    severity="warning",
                    message=(
                        f"Item '{item.raw_name}' has low OCR confidence ({item.confidence:.2f})."
                    ),
                )
            )
        sum_item_totals += quantize_money(item.total_price)
        sum_item_discounts += quantize_money(item.discount_amount)

    # Basket-level discount beyond individual line discounts
    extra_basket_discount = max(
        Decimal("0.00"),
        quantize_money(draft.discounts_total) - sum_item_discounts,
    )
    exclusive_tax = Decimal("0.00") if draft.tax_included else quantize_money(draft.tax_total)

    expected_receipt_total = quantize_money(
        sum_item_totals
        - extra_basket_discount
        + exclusive_tax
        + quantize_money(draft.container_deposit_total)
        + quantize_money(draft.rounding_adjustment)
    )
    if abs(expected_receipt_total - quantize_money(draft.total)) > HEADER_TOLERANCE:
        warnings.append(
            ValidationWarning(
                field="total",
                code="receipt_total_mismatch",
                severity="warning",
                message=(
                    f"Reconciled items + adjustments ({expected_receipt_total} {draft.currency}) "
                    f"differs from receipt total ({quantize_money(draft.total)} {draft.currency})."
                ),
            )
        )

    return warnings


def normalize_and_validate_extraction(
    extracted: ExtractedReceiptPayload,
) -> tuple[EditableReceiptDraft, list[ValidationWarning]]:
    """Separate SGR deposit lines from product items and build an initial EditableReceiptDraft."""
    product_items: list[EditableDraftItem] = []
    separated_deposit = quantize_money(extracted.container_deposit_total)

    for item in extracted.items:
        if is_sgr_deposit_item(item.raw_name, item.is_deposit_line):
            separated_deposit += quantize_money(item.total_price)
            continue

        product_items.append(
            EditableDraftItem(
                raw_name=item.raw_name.strip()[:255],
                normalized_name=(item.normalized_name.strip() or item.raw_name.strip())[:255],
                brand=item.brand.strip()[:120] if item.brand else None,
                category_slug=item.category_slug,
                quantity=item.quantity,
                unit=item.unit,
                package_size=item.package_size,
                package_unit=item.package_unit,
                unit_price=item.unit_price,
                discount_amount=quantize_money(item.discount_amount),
                total_price=quantize_money(item.total_price),
                confidence=item.confidence,
            )
        )

    subtotal = quantize_money(extracted.subtotal)
    if subtotal == Decimal("0.00") and product_items:
        subtotal = sum(
            (quantize_money(i.quantity * i.unit_price) for i in product_items),
            Decimal("0.00"),
        )

    draft = EditableReceiptDraft(
        store_name=(extracted.store_name or "Unknown Store").strip()[:200],
        branch_name=extracted.branch_name.strip()[:200] if extracted.branch_name else None,
        store_cui=extracted.store_cui.strip()[:64] if extracted.store_cui else None,
        receipt_number=extracted.receipt_number.strip()[:120] if extracted.receipt_number else None,
        purchase_date=extracted.purchase_date,
        currency=extracted.currency,
        subtotal=subtotal,
        discounts_total=quantize_money(extracted.discounts_total),
        tax_total=quantize_money(extracted.tax_total),
        tax_included=extracted.tax_included,
        container_deposit_total=separated_deposit,
        rounding_adjustment=quantize_money(extracted.rounding_adjustment),
        total=quantize_money(extracted.total),
        items=product_items,
    )
    warnings = validate_editable_draft(draft)
    return draft, warnings

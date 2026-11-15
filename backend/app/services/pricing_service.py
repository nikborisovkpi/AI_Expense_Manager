"""Deterministic unit normalization and dual-pricing calculation service."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ALLOWED_PACKAGE_UNITS = frozenset({"piece", "pack", "pair", "g", "kg", "ml", "l"})
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
SIX_PLACES = Decimal("0.000001")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def quantize_unit_price(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def normalize_measurement(package_size: Decimal, package_unit: str) -> tuple[str, Decimal]:
    """Convert package size & unit into canonical standard_unit ('kg', 'l', or count unit)."""
    unit = package_unit.strip().lower()
    if unit not in ALLOWED_PACKAGE_UNITS:
        raise ValueError(f"Unsupported measurement unit: {package_unit!r}")
    if package_size <= Decimal("0"):
        raise ValueError("Package size must be strictly positive")

    if unit == "g":
        return "kg", (package_size / Decimal("1000")).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
    if unit == "ml":
        return "l", (package_size / Decimal("1000")).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
    return unit, package_size.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ItemPriceInput:
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = Decimal("0.00")
    total_price: Decimal | None = None
    standard_quantity: Decimal | None = None


@dataclass(frozen=True)
class PricedItemResult:
    total_price: Decimal
    effective_total_price: Decimal
    regular_standard_unit_price: Decimal | None
    paid_standard_unit_price: Decimal | None


def allocate_purchase_items_pricing(
    *,
    items: list[ItemPriceInput],
    final_amount: Decimal,
) -> list[PricedItemResult]:
    """Compute exact effective spend per item and both regular & paid standard unit prices.

    - `effective_total_price` sums exactly (to 0.01) to `final_amount` when `items` is non-empty,
      pro-rata allocating basket-level discounts, deposits, taxes, and rounding.
    - `regular_standard_unit_price` uses ORIGINAL pre-discount `unit_price / standard_quantity`
      for unbiased store-chain comparisons (e.g., RON/kg or RON/l).
    - `paid_standard_unit_price` uses `effective_total_price / (quantity * standard_quantity)`.
    """
    if not items:
        return []

    target_amount = quantize_money(final_amount)
    line_totals: list[Decimal] = []
    for item in items:
        if item.total_price is not None:
            line_totals.append(quantize_money(item.total_price))
        else:
            gross = item.quantity * item.unit_price
            net_line = quantize_money(gross - item.discount_amount)
            line_totals.append(max(Decimal("0.00"), net_line))

    sum_line_totals = sum(line_totals, Decimal("0.00"))
    effective_totals: list[Decimal] = []

    if sum_line_totals > Decimal("0.00"):
        for lt in line_totals:
            share = (lt / sum_line_totals) * target_amount
            effective_totals.append(quantize_money(share))
    else:
        equal_share = quantize_money(target_amount / Decimal(len(items)))
        effective_totals = [equal_share for _ in items]

    # Place any penny rounding remainder deterministically on the largest line item
    remainder = target_amount - sum(effective_totals, Decimal("0.00"))
    if remainder != Decimal("0.00"):
        largest_idx = max(range(len(effective_totals)), key=lambda idx: line_totals[idx])
        effective_totals[largest_idx] = quantize_money(effective_totals[largest_idx] + remainder)

    results: list[PricedItemResult] = []
    for idx, item in enumerate(items):
        std_qty = item.standard_quantity
        reg_std_price: Decimal | None = None
        paid_std_price: Decimal | None = None

        if std_qty is not None and std_qty > Decimal("0") and item.quantity > Decimal("0"):
            reg_std_price = quantize_unit_price(item.unit_price / std_qty)
            total_std_units = item.quantity * std_qty
            paid_std_price = quantize_unit_price(effective_totals[idx] / total_std_units)

        results.append(
            PricedItemResult(
                total_price=line_totals[idx],
                effective_total_price=effective_totals[idx],
                regular_standard_unit_price=reg_std_price,
                paid_standard_unit_price=paid_std_price,
            )
        )

    return results

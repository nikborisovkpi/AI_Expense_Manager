"""Unit tests for deterministic unit normalization and dual-pricing calculations."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.pricing_service import (
    ItemPriceInput,
    allocate_purchase_items_pricing,
    normalize_measurement,
)


def test_normalize_measurement_converts_grams_and_milliliters() -> None:
    std_unit_g, std_qty_g = normalize_measurement(Decimal("250"), "g")
    assert std_unit_g == "kg"
    assert std_qty_g == Decimal("0.250000")

    std_unit_ml, std_qty_ml = normalize_measurement(Decimal("400"), "ml")
    assert std_unit_ml == "l"
    assert std_qty_ml == Decimal("0.400000")

    std_unit_l, std_qty_l = normalize_measurement(Decimal("1.5"), "l")
    assert std_unit_l == "l"
    assert std_qty_l == Decimal("1.500000")

    std_unit_pc, std_qty_pc = normalize_measurement(Decimal("10"), "piece")
    assert std_unit_pc == "piece"
    assert std_qty_pc == Decimal("10.000000")


def test_normalize_measurement_rejects_invalid_unit_or_zero_size() -> None:
    with pytest.raises(ValueError, match="Unsupported measurement unit"):
        normalize_measurement(Decimal("1"), "gallon")

    with pytest.raises(ValueError, match="positive"):
        normalize_measurement(Decimal("0"), "kg")


def test_dual_pricing_reconciles_effective_spend_and_preserves_regular_price() -> None:
    """Review Focus #1:
    - Milk 1.5L: qty=2, regular=10.00 RON, line discount=3.00 RON -> total=17.00 RON
    - Cheese 250g: qty=1, regular=12.00 RON, line discount=0.00 RON -> total=12.00 RON
    - Basket voucher=-2.00 RON, SGR deposit=+1.00 RON, rounding=+0.01 RON
    - Final receipt amount = (17.00 + 12.00) - 2.00 + 1.00 + 0.01 = 28.01 RON
    """
    items = [
        ItemPriceInput(
            quantity=Decimal("2.000"),
            unit_price=Decimal("10.0000"),
            discount_amount=Decimal("3.00"),
            standard_quantity=Decimal("1.500000"),
        ),
        ItemPriceInput(
            quantity=Decimal("1.000"),
            unit_price=Decimal("12.0000"),
            discount_amount=Decimal("0.00"),
            standard_quantity=Decimal("0.250000"),
        ),
    ]

    priced = allocate_purchase_items_pricing(
        items=items,
        final_amount=Decimal("28.01"),
    )

    assert len(priced) == 2
    assert priced[0].total_price == Decimal("17.00")
    assert priced[1].total_price == Decimal("12.00")

    # Exact penny reconciliation with purchases.amount
    assert sum(p.effective_total_price for p in priced) == Decimal("28.01")

    # Store comparison baseline uses ORIGINAL pre-discount regular price per kg / l:
    # Milk: 10.00 RON / 1.5 L = 6.6667 RON/l (NOT reduced by 3.00 line discount or 2.00 voucher!)
    assert priced[0].regular_standard_unit_price == Decimal("6.6667")
    # Cheese: 12.00 RON / 0.25 kg = 48.0000 RON/kg
    assert priced[1].regular_standard_unit_price == Decimal("48.0000")

    # Paid effective unit price reflects all discounts + adjustments
    assert priced[0].paid_standard_unit_price is not None
    assert priced[0].paid_standard_unit_price < priced[0].regular_standard_unit_price

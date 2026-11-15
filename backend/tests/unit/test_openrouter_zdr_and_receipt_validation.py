"""Phase 5 unit tests: OpenRouter ZDR client, PDF render, SGR & arithmetic validation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pypdfium2 as pdfium
import pytest
from pydantic import BaseModel

from app.ai.client import OpenRouterZDRClient
from app.ai.receipt.pdf_converter import render_pdf_bytes_to_png_pages
from app.ai.receipt.schemas import ExtractedLineItem, ExtractedReceiptPayload
from app.ai.receipt.validator import normalize_and_validate_extraction
from app.core.config import Settings
from app.core.errors import AppError


class SimpleStructuredOut(BaseModel):
    store: str
    total: Decimal


async def test_openrouter_client_enforces_zdr_on_primary_and_fallbacks() -> None:
    captured_requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append(body)
        # Simulate primary Claude unavailable under strict parameter check; GPT fallback succeeds
        if body["model"] == "anthropic/claude-sonnet-4.6":
            return httpx.Response(
                404,
                json={"error": {"message": "No ZDR endpoints found for requested parameters"}},
            )
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": '{"store": "Kaufland", "total": "42.50"}'}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 25, "total_tokens": 145},
            },
        )

    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="test-or-key",
        OPENROUTER_MODEL="anthropic/claude-sonnet-4.6",
        OPENROUTER_FALLBACK_MODELS="openai/gpt-4.1-mini",
    )
    client = OpenRouterZDRClient(settings, transport=httpx.MockTransport(handler))
    result = await client.generate_structured(
        system_prompt="Extract summary.",
        user_prompt="Kaufland 42.50 RON",
        response_model=SimpleStructuredOut,
    )

    assert result.parsed.store == "Kaufland"
    assert result.parsed.total == Decimal("42.50")
    assert result.model_used == "openai/gpt-4.1-mini"
    assert len(captured_requests) == 2

    for req_body in captured_requests:
        assert req_body["provider"] == {
            "zdr": True,
            "data_collection": "deny",
            "require_parameters": True,
        }
        assert "response_format" in req_body


async def test_openrouter_client_fails_closed_when_all_zdr_models_fail() -> None:
    def failing_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "No ZDR provider available"}})

    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="test-or-key",
        OPENROUTER_MODEL="anthropic/claude-sonnet-4.6",
        OPENROUTER_FALLBACK_MODELS="openai/gpt-4.1-mini",
    )
    client = OpenRouterZDRClient(settings, transport=httpx.MockTransport(failing_handler))

    with pytest.raises(AppError) as exc_info:
        await client.generate_structured(
            system_prompt="Extract",
            user_prompt="Receipt",
            response_model=SimpleStructuredOut,
        )
    assert exc_info.value.status_code == 503


def test_pdf_converter_renders_in_memory_png_without_disk_writes() -> None:
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 300)
    import io

    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()

    pages = render_pdf_bytes_to_png_pages(buf.getvalue())
    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_sgr_separation_and_arithmetic_mismatch_detection() -> None:
    extracted = ExtractedReceiptPayload(
        store_name="Kaufland Romania",
        purchase_date="2026-11-14T18:20:00+02:00",
        currency="RON",
        subtotal=Decimal("10.00"),
        discounts_total=Decimal("0.00"),
        tax_total=Decimal("0.83"),
        container_deposit_total=Decimal("0.00"),
        rounding_adjustment=Decimal("0.00"),
        total=Decimal("11.00"),
        items=[
            ExtractedLineItem(
                raw_name="APA PLATA BORSEC 2L",
                normalized_name="Mineral Water 2L",
                brand="Borsec",
                category_slug="water",
                quantity=Decimal("2"),
                unit="piece",
                package_size=Decimal("2"),
                package_unit="l",
                unit_price=Decimal("5.00"),
                discount_amount=Decimal("0.00"),
                total_price=Decimal("10.00"),
                is_deposit_line=False,
                confidence=0.96,
            ),
            ExtractedLineItem(
                raw_name="GARANTIE SGR 2X0.50",
                normalized_name="SGR Deposit",
                quantity=Decimal("2"),
                unit="piece",
                package_size=Decimal("1"),
                package_unit="piece",
                unit_price=Decimal("0.50"),
                discount_amount=Decimal("0.00"),
                total_price=Decimal("1.00"),
                is_deposit_line=True,
                confidence=0.99,
            ),
        ],
    )

    clean_draft, warnings = normalize_and_validate_extraction(extracted)
    # SGR line separated out of product items into container_deposit_total = 1.00 RON
    assert len(clean_draft.items) == 1
    assert clean_draft.container_deposit_total == Decimal("1.00")
    assert warnings == []

    # Now introduce a 5.00 RON arithmetic discrepancy -> must flag total_mismatch warning
    bad_extracted = extracted.model_copy(update={"total": Decimal("16.00")})
    _, bad_warnings = normalize_and_validate_extraction(bad_extracted)
    warning_codes = {w.code for w in bad_warnings}
    assert "receipt_total_mismatch" in warning_codes

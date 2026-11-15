"""Provider-agnostic OpenRouter ZDR client with fallback routing and daily token budgets."""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, RateLimitError
from app.models.agent import AIUsageDaily

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class StructuredGenerationResult[T: BaseModel]:
    parsed: T
    raw_response: dict[str, Any]
    model_used: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def build_zdr_provider_preferences(settings: Settings) -> dict[str, Any]:
    """Mandatory OpenRouter ZDR routing preferences (never relaxed on fallbacks)."""
    return {
        "zdr": settings.openrouter_provider_zdr,
        "data_collection": settings.openrouter_data_collection,
        "require_parameters": settings.openrouter_require_parameters,
    }


async def check_and_record_daily_ai_budget(
    session: AsyncSession,
    user_id: uuid.UUID,
    settings: Settings,
    *,
    tokens_used: int = 0,
    increment_request: bool = True,
) -> None:
    """Enforce per-installation daily AI request and token budgets."""
    today = datetime.now(UTC).date()
    usage = await session.scalar(
        select(AIUsageDaily).where(
            AIUsageDaily.user_id == user_id,
            AIUsageDaily.usage_date == today,
        )
    )
    if usage is None:
        usage = AIUsageDaily(
            user_id=user_id,
            usage_date=today,
            request_count=0,
            total_tokens=0,
        )
        session.add(usage)
        await session.flush()

    if increment_request and usage.request_count >= settings.ai_daily_request_limit:
        raise RateLimitError("Daily AI request limit reached for this installation.")
    if usage.total_tokens >= settings.ai_daily_token_budget:
        raise RateLimitError("Daily AI token budget reached for this installation.")

    if increment_request:
        usage.request_count += 1
    if tokens_used > 0:
        usage.total_tokens += tokens_used
    await session.flush()


class OpenRouterZDRClient:
    """Provider-agnostic OpenRouter chat/vision structured output client."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def _candidate_models(self, primary_model: str) -> list[str]:
        candidates = [primary_model.strip()]
        for fb in self._settings.fallback_models_list:
            if fb not in candidates:
                candidates.append(fb)
        return candidates

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "AI Expense Manager",
        }

    async def _post_completion(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self._settings.openrouter_base_url.rstrip('/')}/chat/completions"
        client_kwargs: dict[str, Any] = {"timeout": self._settings.ai_run_timeout_seconds}
        if self._transport is not None:
            if isinstance(self._transport, httpx.AsyncBaseTransport):
                client_kwargs["transport"] = self._transport
            else:
                # Wrap sync MockTransport cleanly for httpx.AsyncClient tests
                return httpx.Client(transport=self._transport).post(
                    url,
                    headers=self._headers(),
                    json=payload,
                )
        async with httpx.AsyncClient(**client_kwargs) as client:
            return await client.post(url, headers=self._headers(), json=payload)

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[SchemaT],
        primary_model: str | None = None,
        images: list[tuple[bytes, str]] | None = None,
    ) -> StructuredGenerationResult[SchemaT]:
        if not self._settings.openrouter_api_key:
            raise AppError(
                status_code=503,
                code="ai_provider_unconfigured",
                message="OPENROUTER_API_KEY is not configured.",
            )

        chosen_primary = primary_model or self._settings.openrouter_model
        candidates = self._candidate_models(chosen_primary)
        provider_prefs = build_zdr_provider_preferences(self._settings)

        user_content: str | list[dict[str, Any]]
        if images:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
            for img_bytes, mime in images:
                b64 = base64.b64encode(img_bytes).decode("ascii")
                blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )
            user_content = blocks
        else:
            user_content = user_prompt

        json_schema = response_model.model_json_schema()
        last_error_reason = "No compliant ZDR endpoint succeeded."

        for model_id in candidates:
            started = time.perf_counter()
            payload: dict[str, Any] = {
                "model": model_id,
                "provider": provider_prefs,
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            }

            try:
                res = await self._post_completion(payload)
            except httpx.HTTPError as exc:
                last_error_reason = f"Network error for {model_id}: {type(exc).__name__}"
                continue

            if res.status_code >= 400:
                last_error_reason = f"Model {model_id} rejected request with HTTP {res.status_code}"
                continue

            try:
                body = res.json()
                raw_text = body["choices"][0]["message"]["content"]
                parsed = response_model.model_validate_json(
                    raw_text if isinstance(raw_text, str) else json.dumps(raw_text)
                )
            except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
                last_error_reason = (
                    f"Invalid structured output from {model_id}: {type(exc).__name__}"
                )
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)
            usage = body.get("usage") or {}
            return StructuredGenerationResult(
                parsed=parsed,
                raw_response=body,
                model_used=str(body.get("model") or model_id),
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=latency_ms,
            )

        raise AppError(
            status_code=503,
            code="ai_provider_unavailable",
            message="No compliant ZDR OpenRouter endpoint succeeded for the requested parameters.",
            details={"reason": last_error_reason},
        )

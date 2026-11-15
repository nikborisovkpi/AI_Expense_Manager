"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SupportedCurrency = Literal["RON", "UAH", "EUR", "USD"]
ALLOWED_CURRENCIES: tuple[str, ...] = ("RON", "UAH", "EUR", "USD")


class Settings(BaseSettings):
    """Typed backend settings aligned with Section 14 of the blueprint."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development", alias="ENVIRONMENT")
    app_version: str = "0.1.0"
    backend_host: str = Field(default="127.0.0.1", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )

    default_currency: SupportedCurrency = "RON"
    default_locale: str = "en"

    # Database & Private Supabase Storage (Backend-only; NO Supabase Auth/JWT)
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_expense_manager",
        alias="DATABASE_URL",
    )
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_secret_key: str = Field(default="", alias="SUPABASE_SECRET_KEY")
    supabase_receipts_bucket: str = Field(default="receipts", alias="SUPABASE_RECEIPTS_BUCKET")
    supabase_avatars_bucket: str = Field(default="avatars", alias="SUPABASE_AVATARS_BUCKET")

    # Provider-agnostic OpenRouter under strict ZDR
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_model: str = Field(
        default="anthropic/claude-sonnet-4.6",
        alias="OPENROUTER_MODEL",
    )
    openrouter_vision_model: str = Field(
        default="anthropic/claude-sonnet-4.6",
        alias="OPENROUTER_VISION_MODEL",
    )
    openrouter_classification_model: str = Field(
        default="anthropic/claude-haiku-4.5",
        alias="OPENROUTER_CLASSIFICATION_MODEL",
    )
    openrouter_fallback_models: str = Field(
        default="openai/gpt-4.1-mini,openai/gpt-4.1",
        alias="OPENROUTER_FALLBACK_MODELS",
    )
    openrouter_provider_zdr: bool = Field(default=True, alias="OPENROUTER_PROVIDER_ZDR")
    openrouter_data_collection: str = Field(default="deny", alias="OPENROUTER_DATA_COLLECTION")
    openrouter_require_parameters: bool = Field(
        default=True,
        alias="OPENROUTER_REQUIRE_PARAMETERS",
    )

    # Receipt worker & watchdog
    receipt_processing_timeout_seconds: int = Field(
        default=120,
        alias="RECEIPT_PROCESSING_TIMEOUT_SECONDS",
    )
    receipt_max_attempts: int = Field(default=3, alias="RECEIPT_MAX_ATTEMPTS")
    receipt_worker_poll_interval_seconds: float = Field(
        default=3.0,
        alias="RECEIPT_WORKER_POLL_INTERVAL_SECONDS",
    )
    receipt_worker_concurrency: int = Field(default=1, alias="RECEIPT_WORKER_CONCURRENCY")
    receipt_watchdog_interval_seconds: float = Field(
        default=30.0,
        alias="RECEIPT_WATCHDOG_INTERVAL_SECONDS",
    )
    receipt_max_file_size_bytes: int = 15 * 1024 * 1024  # 15 MB

    # AI safety & execution limits
    ai_daily_request_limit: int = Field(default=200, alias="AI_DAILY_REQUEST_LIMIT")
    ai_daily_token_budget: int = Field(default=500_000, alias="AI_DAILY_TOKEN_BUDGET")
    ai_agent_max_steps: int = Field(default=8, alias="AI_AGENT_MAX_STEPS")
    ai_tool_timeout_seconds: float = Field(default=15.0, alias="AI_TOOL_TIMEOUT_SECONDS")
    ai_run_timeout_seconds: float = Field(default=60.0, alias="AI_RUN_TIMEOUT_SECONDS")

    # Observability
    logfire_token: str = Field(default="", alias="LOGFIRE_TOKEN")
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")

    @field_validator("openrouter_provider_zdr")
    @classmethod
    def _enforce_zdr(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Zero Data Retention (OPENROUTER_PROVIDER_ZDR=true) is mandatory.")
        return value

    @field_validator("openrouter_data_collection")
    @classmethod
    def _enforce_data_collection_deny(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "deny":
            raise ValueError("OPENROUTER_DATA_COLLECTION (data_collection) must be 'deny'.")
        return normalized

    @field_validator("openrouter_require_parameters")
    @classmethod
    def _enforce_require_parameters(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "OPENROUTER_REQUIRE_PARAMETERS=true (require_parameters) is mandatory."
            )
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def fallback_models_list(self) -> list[str]:
        return [item.strip() for item in self.openrouter_fallback_models.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

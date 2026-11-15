"""Pydantic API schemas for receipt upload, status, review draft, and confirmation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.receipt.schemas import EditableReceiptDraft, ValidationWarning


class ReceiptSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_id: uuid.UUID | None
    original_filename: str | None
    file_type: str
    file_size_bytes: int
    status: str
    attempt_count: int
    max_attempts: int
    extraction_error: str | None
    created_at: datetime
    updated_at: datetime


class ReceiptStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    attempt_count: int
    max_attempts: int
    processing_started_at: datetime | None
    processing_lease_expires_at: datetime | None
    extraction_error: str | None
    purchase_id: uuid.UUID | None
    updated_at: datetime


class ReceiptResultResponse(BaseModel):
    id: uuid.UUID
    status: str
    purchase_id: uuid.UUID | None
    model_name: str | None
    prompt_version: str | None
    extracted_data: dict[str, Any] | None
    editable_draft: EditableReceiptDraft | None
    validation_warnings: list[ValidationWarning] = Field(default_factory=list)
    extraction_error: str | None
    created_at: datetime
    updated_at: datetime


class ReceiptConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    draft: EditableReceiptDraft | None = None

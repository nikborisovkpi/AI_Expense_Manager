"""Durable receipt queue and extraction state model (Section 5.1 & 7.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONVariant, utcnow

RECEIPT_STATUSES = (
    "uploaded",
    "queued",
    "processing",
    "extracted",
    "needs_review",
    "confirmed",
    "failed",
    "cancelled",
)


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'uploaded', 'queued', 'processing', 'extracted', "
            "'needs_review', 'confirmed', 'failed', 'cancelled'"
            ")",
            name="receipt_status_allowed",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_receipts_user_idempotency"),
        Index("ix_receipts_user_status", "user_id", "status"),
        Index("ix_receipts_user_file_hash", "user_id", "file_hash"),
        Index("ix_receipts_fingerprint", "receipt_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchases.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    store_cui: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="uploaded")
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    raw_model_response: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    editable_draft: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    validation_warnings: Mapped[list[Any] | None] = mapped_column(JSONVariant, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

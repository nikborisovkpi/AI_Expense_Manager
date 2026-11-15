"""Watchdog recovering expired in-process receipt processing leases (Section 7.1)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models.receipt import Receipt


async def recover_expired_receipt_leases(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Requeue or fail receipts whose processing lease has expired."""
    now = utcnow()
    async with session_factory() as session:
        expired_rows = list(
            (
                await session.scalars(
                    select(Receipt).where(
                        Receipt.status == "processing",
                        Receipt.processing_lease_expires_at.is_not(None),
                        Receipt.processing_lease_expires_at <= now,
                    )
                )
            ).all()
        )
        if not expired_rows:
            return 0

        for rec in expired_rows:
            rec.processing_lease_expires_at = None
            if rec.attempt_count >= rec.max_attempts:
                rec.status = "failed"
                rec.extraction_error = (
                    "Receipt processing timed out and reached the maximum retry limit."
                )
            else:
                rec.status = "queued"
                rec.extraction_error = "Recovered stale processing lease; queued for retry."

        await session.commit()
        return len(expired_rows)

"""Initial MVP schema for AI Expense Manager.

Revision ID: 0001_initial_mvp_schema
Revises: None
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import app.models  # noqa: F401
from alembic import op
from app.db.base import Base

revision: str = "0001_initial_mvp_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # Partial unique index for active/confirmed receipt file hashes in PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_receipts_active_file_hash "
            "ON receipts (user_id, file_hash) "
            "WHERE status NOT IN ('cancelled', 'failed')"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_receipts_active_file_hash")
    Base.metadata.drop_all(bind=bind)

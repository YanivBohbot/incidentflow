"""add pending human review to investigations

Revision ID: d3e9a6b1f4c7
Revises: e7f6a5b4c3d2
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3e9a6b1f4c7"
down_revision: str | Sequence[str] | None = "e7f6a5b4c3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE investigation_lifecycle "
        "ADD VALUE IF NOT EXISTS 'AWAITING_HUMAN_REVIEW'"
    )
    op.add_column(
        "investigations",
        sa.Column("pending_human_review_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("investigations", "pending_human_review_payload")
    # PostgreSQL enum values cannot be safely removed in place.

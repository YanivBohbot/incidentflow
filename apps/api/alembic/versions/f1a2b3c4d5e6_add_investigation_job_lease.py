"""add investigation job lease columns

Revision ID: f1a2b3c4d5e6
Revises: d3e9a6b1f4c7
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "d3e9a6b1f4c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("investigations", sa.Column("lease_token", sa.String(36), nullable=True))
    op.add_column(
        "investigations",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("investigations", sa.Column("pending_resume_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("investigations", "pending_resume_payload")
    op.drop_column("investigations", "attempt_count")
    op.drop_column("investigations", "lease_expires_at")
    op.drop_column("investigations", "lease_token")

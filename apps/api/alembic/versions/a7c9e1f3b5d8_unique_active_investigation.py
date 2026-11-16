"""unique active investigation per incident

Revision ID: a7c9e1f3b5d8
Revises: f1a2b3c4d5e6
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c9e1f3b5d8"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_PREDICATE = "lifecycle IN ('PENDING', 'RUNNING')"


def upgrade() -> None:
    op.create_index(
        "uq_investigations_active_incident",
        "investigations",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_PREDICATE),
        sqlite_where=sa.text(ACTIVE_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_investigations_active_incident", table_name="investigations")

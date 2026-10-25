"""create investigations table

Revision ID: cf5c59ed1431
Revises: 6b80d6dbbc03
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cf5c59ed1431"
down_revision: str | Sequence[str] | None = "6b80d6dbbc03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("incident_request", sa.Text(), nullable=False),
        sa.Column("incident_business_status", sa.String(length=50), nullable=False),
        sa.Column(
            "lifecycle",
            sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="investigation_lifecycle"),
            nullable=False,
        ),
        sa.Column("workflow_thread_id", sa.String(length=100), nullable=False),
        sa.Column("report_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_thread_id"),
    )
    op.create_index("ix_investigations_incident_id", "investigations", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_investigations_incident_id", table_name="investigations")
    op.drop_table("investigations")

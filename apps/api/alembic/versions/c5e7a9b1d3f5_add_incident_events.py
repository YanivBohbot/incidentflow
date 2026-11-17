"""add incident events

Revision ID: c5e7a9b1d3f5
Revises: b4d6f8a0c2e4
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5e7a9b1d3f5"
down_revision: str | Sequence[str] | None = "b4d6f8a0c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("investigations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("reconstructed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_incident_events_occurred_at", "incident_events", ["occurred_at"])
    op.create_index(
        "ix_incident_events_incident_time", "incident_events", ["incident_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_incident_events_incident_time", table_name="incident_events")
    op.drop_index("ix_incident_events_occurred_at", table_name="incident_events")
    op.drop_table("incident_events")

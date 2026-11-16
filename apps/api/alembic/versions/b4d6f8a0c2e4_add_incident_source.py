"""add incident source, service and external id

Revision ID: b4d6f8a0c2e4
Revises: a7c9e1f3b5d8
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b4d6f8a0c2e4"
down_revision: str | Sequence[str] | None = "a7c9e1f3b5d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN_INCIDENT_PREDICATE = (
    "external_id IS NOT NULL AND status IN ('OPEN', 'INVESTIGATING', 'PENDING_APPROVAL')"
)


def upgrade() -> None:
    incident_source = postgresql.ENUM("MANUAL", "CLOUDWATCH_ALARM", name="incident_source")
    incident_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "incidents",
        sa.Column(
            "source",
            postgresql.ENUM(name="incident_source", create_type=False),
            nullable=False,
            server_default="MANUAL",
        ),
    )
    op.add_column("incidents", sa.Column("service", sa.String(length=200), nullable=True))
    op.add_column("incidents", sa.Column("external_id", sa.String(length=512), nullable=True))
    op.create_index(
        "uq_incidents_open_external",
        "incidents",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text(OPEN_INCIDENT_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_incidents_open_external", table_name="incidents")
    op.drop_column("incidents", "external_id")
    op.drop_column("incidents", "service")
    op.drop_column("incidents", "source")
    postgresql.ENUM(name="incident_source").drop(op.get_bind(), checkfirst=True)

"""add curated incident lessons

Revision ID: e7f6a5b4c3d2
Revises: b38f0bf762de
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e7f6a5b4c3d2"
down_revision: str | Sequence[str] | None = "b38f0bf762de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    incident_lesson_state = postgresql.ENUM(
        "PENDING_INDEX",
        "CONFIRMED",
        "INDEX_FAILED",
        name="incident_lesson_state",
        create_type=False,
    )
    incident_lesson_state.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "incident_lessons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("service", sa.String(length=200), nullable=False),
        sa.Column("environment", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=True),
        sa.Column("confirmed_root_cause", sa.Text(), nullable=False),
        sa.Column("validated_resolution", sa.Text(), nullable=False),
        sa.Column("state", incident_lesson_state, nullable=False),
        sa.Column("vector_id", sa.String(length=200), nullable=True),
        sa.Column("index_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vector_id"),
    )
    op.create_index("ix_incident_lessons_investigation_id", "incident_lessons", ["investigation_id"])
    op.create_index("ix_incident_lessons_service", "incident_lessons", ["service"])
    op.create_index("ix_incident_lessons_environment", "incident_lessons", ["environment"])
    op.create_index("ix_incident_lessons_tenant_id", "incident_lessons", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_lessons_tenant_id", table_name="incident_lessons")
    op.drop_index("ix_incident_lessons_environment", table_name="incident_lessons")
    op.drop_index("ix_incident_lessons_service", table_name="incident_lessons")
    op.drop_index("ix_incident_lessons_investigation_id", table_name="incident_lessons")
    op.drop_table("incident_lessons")
    sa.Enum(name="incident_lesson_state").drop(op.get_bind(), checkfirst=True)

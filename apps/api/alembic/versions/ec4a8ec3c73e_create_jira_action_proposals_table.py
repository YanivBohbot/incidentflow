"""create jira action proposals table

Revision ID: ec4a8ec3c73e
Revises: cf5c59ed1431
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ec4a8ec3c73e"
down_revision: str | Sequence[str] | None = "cf5c59ed1431"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jira_action_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            sa.Enum("CREATE_ISSUE", "ADD_COMMENT", name="jira_proposal_action"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "PENDING", "EXECUTING", "EXECUTED", "FAILED", "REJECTED",
                name="jira_proposal_state",
            ),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jira_action_proposals_investigation_id",
        "jira_action_proposals",
        ["investigation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_jira_action_proposals_investigation_id", table_name="jira_action_proposals")
    op.drop_table("jira_action_proposals")

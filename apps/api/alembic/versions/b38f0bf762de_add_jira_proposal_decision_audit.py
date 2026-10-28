"""add Jira proposal decision audit

Revision ID: b38f0bf762de
Revises: ec4a8ec3c73e
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b38f0bf762de"
down_revision: str | Sequence[str] | None = "ec4a8ec3c73e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE jira_proposal_state ADD VALUE IF NOT EXISTS 'CANCELLED'")
    op.add_column("jira_action_proposals", sa.Column("rejected_at", sa.DateTime(timezone=True)))
    op.add_column("jira_action_proposals", sa.Column("rejected_by", sa.String(length=200)))
    op.add_column("jira_action_proposals", sa.Column("rejection_reason", sa.Text()))
    op.add_column("jira_action_proposals", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.add_column("jira_action_proposals", sa.Column("cancelled_by", sa.String(length=200)))
    op.add_column("jira_action_proposals", sa.Column("cancellation_reason", sa.Text()))
    op.add_column(
        "jira_action_proposals",
        sa.Column("proposed_by", sa.String(length=200), nullable=False, server_default="local-operator"),
    )
    op.add_column(
        "jira_action_proposals",
        sa.Column("decision_history", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.alter_column("jira_action_proposals", "proposed_by", server_default=None)
    op.alter_column("jira_action_proposals", "decision_history", server_default=None)


def downgrade() -> None:
    op.drop_column("jira_action_proposals", "decision_history")
    op.drop_column("jira_action_proposals", "proposed_by")
    op.drop_column("jira_action_proposals", "cancellation_reason")
    op.drop_column("jira_action_proposals", "cancelled_by")
    op.drop_column("jira_action_proposals", "cancelled_at")
    op.drop_column("jira_action_proposals", "rejection_reason")
    op.drop_column("jira_action_proposals", "rejected_by")
    op.drop_column("jira_action_proposals", "rejected_at")

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from incidentflow.domain.jira.models import (
    JiraActionProposal,
    JiraProposalAction,
    JiraProposalState,
)
from incidentflow.infrastructure.database.models import JiraActionProposalORM


class JiraProposalRepository:
    """Persistence boundary for auditable, one-time Jira action approvals."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def to_domain(orm: JiraActionProposalORM) -> JiraActionProposal:
        return JiraActionProposal.model_validate(
            {
                "id": orm.id,
                "investigation_id": orm.investigation_id,
                "action": orm.action,
                "state": orm.state,
                "payload": orm.payload,
                "result_payload": orm.result_payload,
                "error_message": orm.error_message,
                "approved_at": orm.approved_at,
                "approved_by": orm.approved_by,
                "created_at": orm.created_at,
                "updated_at": orm.updated_at,
            }
        )

    def create(
        self,
        investigation_id: UUID,
        action: JiraProposalAction,
        payload: dict[str, str],
    ) -> JiraActionProposal:
        orm = JiraActionProposalORM(
            investigation_id=investigation_id,
            action=action,
            payload=payload,
        )
        self.session.add(orm)
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def get(self, proposal_id: UUID) -> JiraActionProposal | None:
        orm = self.session.get(JiraActionProposalORM, proposal_id)
        return self.to_domain(orm) if orm is not None else None

    def list_for_investigation(self, investigation_id: UUID) -> list[JiraActionProposal]:
        statement = (
            select(JiraActionProposalORM)
            .where(JiraActionProposalORM.investigation_id == investigation_id)
            .order_by(JiraActionProposalORM.created_at.desc())
        )
        return [self.to_domain(orm) for orm in self.session.scalars(statement).all()]

    def claim_for_execution(
        self, proposal_id: UUID, approved_by: str
    ) -> JiraActionProposal | None:
        """Transition PENDING -> EXECUTING before the external mutation is invoked."""
        statement = (
            update(JiraActionProposalORM)
            .where(
                JiraActionProposalORM.id == proposal_id,
                JiraActionProposalORM.state == JiraProposalState.PENDING,
            )
            .values(
                state=JiraProposalState.EXECUTING,
                approved_at=datetime.now(UTC),
                approved_by=approved_by,
                error_message=None,
            )
        )
        result = self.session.execute(statement)
        if result.rowcount != 1:
            self.session.rollback()
            return None

        self.session.commit()
        orm = self.session.get(JiraActionProposalORM, proposal_id)
        if orm is None:
            return None
        self.session.refresh(orm)
        return self.to_domain(orm)

    def mark_executed(
        self, proposal_id: UUID, result_payload: dict[str, object]
    ) -> JiraActionProposal | None:
        orm = self.session.get(JiraActionProposalORM, proposal_id)
        if orm is None:
            return None
        orm.state = JiraProposalState.EXECUTED
        orm.result_payload = result_payload
        orm.error_message = None
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def mark_failed(self, proposal_id: UUID, error_message: str) -> JiraActionProposal | None:
        orm = self.session.get(JiraActionProposalORM, proposal_id)
        if orm is None:
            return None
        orm.state = JiraProposalState.FAILED
        orm.error_message = error_message
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

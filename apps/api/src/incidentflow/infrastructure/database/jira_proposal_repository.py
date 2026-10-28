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
                "rejected_at": orm.rejected_at,
                "rejected_by": orm.rejected_by,
                "rejection_reason": orm.rejection_reason,
                "cancelled_at": orm.cancelled_at,
                "cancelled_by": orm.cancelled_by,
                "cancellation_reason": orm.cancellation_reason,
                "proposed_by": orm.proposed_by,
                "decision_history": orm.decision_history,
                "created_at": orm.created_at,
                "updated_at": orm.updated_at,
            }
        )

    def create(
        self,
        investigation_id: UUID,
        action: JiraProposalAction,
        payload: dict[str, str],
        proposed_by: str = "local-operator",
    ) -> JiraActionProposal:
        created_at = datetime.now(UTC)
        orm = JiraActionProposalORM(
            investigation_id=investigation_id,
            action=action,
            payload=payload,
            proposed_by=proposed_by,
            decision_history=[
                {"event": "PROPOSED", "actor": proposed_by, "at": created_at.isoformat()}
            ],
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

    def claim_for_execution(self, proposal_id: UUID, approved_by: str) -> JiraActionProposal | None:
        """Atomically transition PENDING -> EXECUTING before the Jira mutation."""
        orm = self.session.get(JiraActionProposalORM, proposal_id, with_for_update=True)
        if orm is None or orm.state is not JiraProposalState.PENDING:
            self.session.rollback()
            return None
        approved_at = datetime.now(UTC)
        orm.state = JiraProposalState.EXECUTING
        orm.approved_at = approved_at
        orm.approved_by = approved_by
        orm.error_message = None
        self._append_history(orm, "APPROVED", approved_by, approved_at)
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def reject(self, proposal_id: UUID, actor: str, reason: str | None) -> JiraActionProposal | None:
        return self._close_pending(
            proposal_id, JiraProposalState.REJECTED, actor, reason, "REJECTED"
        )

    def cancel(self, proposal_id: UUID, actor: str, reason: str | None) -> JiraActionProposal | None:
        return self._close_pending(
            proposal_id, JiraProposalState.CANCELLED, actor, reason, "CANCELLED"
        )

    def _close_pending(
        self,
        proposal_id: UUID,
        state: JiraProposalState,
        actor: str,
        reason: str | None,
        event: str,
    ) -> JiraActionProposal | None:
        orm = self.session.get(JiraActionProposalORM, proposal_id, with_for_update=True)
        if orm is None or orm.state is not JiraProposalState.PENDING:
            self.session.rollback()
            return None
        decided_at = datetime.now(UTC)
        orm.state = state
        if state is JiraProposalState.REJECTED:
            orm.rejected_at, orm.rejected_by, orm.rejection_reason = decided_at, actor, reason
        else:
            orm.cancelled_at, orm.cancelled_by, orm.cancellation_reason = decided_at, actor, reason
        self._append_history(orm, event, actor, decided_at, reason)
        self.session.commit()
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
        self._append_history(orm, "EXECUTED", orm.approved_by or "local-operator", datetime.now(UTC))
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def mark_failed(self, proposal_id: UUID, error_message: str) -> JiraActionProposal | None:
        orm = self.session.get(JiraActionProposalORM, proposal_id)
        if orm is None:
            return None
        orm.state = JiraProposalState.FAILED
        orm.error_message = error_message
        self._append_history(orm, "FAILED", orm.approved_by or "local-operator", datetime.now(UTC), error_message)
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    @staticmethod
    def _append_history(
        orm: JiraActionProposalORM,
        event: str,
        actor: str,
        timestamp: datetime,
        reason: str | None = None,
    ) -> None:
        history = list(orm.decision_history or [])
        entry: dict[str, str] = {"event": event, "actor": actor, "at": timestamp.isoformat()}
        if reason:
            entry["reason"] = reason
        history.append(entry)
        orm.decision_history = history

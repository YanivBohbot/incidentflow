from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.domain.jira.models import (
    JiraIssueCreateRequest,
    JiraProposalAction,
    JiraProposalState,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.jira_proposal_repository import JiraProposalRepository


def _repository() -> JiraProposalRepository:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return JiraProposalRepository(sessionmaker(bind=engine, expire_on_commit=False)())


def test_reject_and_cancel_persist_auditable_pending_decisions() -> None:
    repository = _repository()
    payload = JiraIssueCreateRequest(
        cloudId="cloud-123",
        projectKey="OPS",
        issueType="Incident",
        summary="Payment API errors",
        description="Review before escalation.",
    ).tool_arguments()

    rejected = repository.create(uuid4(), JiraProposalAction.CREATE_ISSUE, payload)
    rejected = repository.reject(rejected.id, "operator-a", "Insufficient evidence")
    assert rejected is not None
    assert rejected.state is JiraProposalState.REJECTED
    assert rejected.rejected_by == "operator-a"
    assert rejected.rejection_reason == "Insufficient evidence"
    assert [entry["event"] for entry in rejected.decision_history] == ["PROPOSED", "REJECTED"]

    cancelled = repository.create(uuid4(), JiraProposalAction.CREATE_ISSUE, payload)
    cancelled = repository.cancel(cancelled.id, "operator-b", "Duplicate proposal")
    assert cancelled is not None
    assert cancelled.state is JiraProposalState.CANCELLED
    assert cancelled.cancelled_by == "operator-b"
    assert cancelled.cancellation_reason == "Duplicate proposal"
    assert [entry["event"] for entry in cancelled.decision_history] == ["PROPOSED", "CANCELLED"]

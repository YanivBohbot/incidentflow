import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.application.services.jira_approval_service import (
    JiraApprovalService,
    JiraProposalNotApprovableError,
)
from incidentflow.domain.jira.models import (
    JiraIssueCreateRequest,
    JiraMCPResult,
    JiraProposalState,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.jira_proposal_repository import JiraProposalRepository


class FakeJiraTicketService:
    def __init__(self) -> None:
        self.created_issues: list[JiraIssueCreateRequest] = []

    async def create_issue(self, request: JiraIssueCreateRequest) -> JiraMCPResult:
        self.created_issues.append(request)
        return JiraMCPResult(operation="createJiraIssue", result={"key": "OPS-42"})


def test_proposal_is_persisted_before_one_time_approval_execution() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    ticket_service = FakeJiraTicketService()
    service = JiraApprovalService(JiraProposalRepository(session), ticket_service)  # type: ignore[arg-type]

    proposal = service.propose_issue(
        investigation_id=uuid4(),
        request=JiraIssueCreateRequest(
            cloudId="cloud-123",
            projectKey="OPS",
            issueType="Incident",
            summary="Payment API is returning HTTP 500",
            description="Created after review in IncidentFlow.",
        ),
    )

    assert proposal.state is JiraProposalState.PENDING
    assert ticket_service.created_issues == []

    executed = asyncio.run(service.approve_and_execute(proposal.id, approved_by="operator-1"))

    assert executed.state is JiraProposalState.EXECUTED
    assert executed.approved_by == "operator-1"
    assert executed.result_payload == {
        "operation": "createJiraIssue",
        "result": {"key": "OPS-42"},
    }
    assert len(ticket_service.created_issues) == 1

    with pytest.raises(JiraProposalNotApprovableError):
        asyncio.run(service.approve_and_execute(proposal.id, approved_by="operator-2"))

    assert len(ticket_service.created_issues) == 1

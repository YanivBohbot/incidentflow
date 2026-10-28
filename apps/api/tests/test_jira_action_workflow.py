from uuid import uuid4

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incidentflow.agent.orchestration.jira_action_workflow import build_jira_action_workflow
from incidentflow.api.routes.jira import approve_proposal, propose_issue
from incidentflow.domain.jira.models import (
    JiraActionProposal,
    JiraIssueCreateRequest,
    JiraProposalAction,
    JiraProposalState,
)


def test_jira_proposal_review_interrupts_and_resumes_with_human_decision() -> None:
    workflow = build_jira_action_workflow(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "jira-proposal:proposal-1"}}

    pending = workflow.invoke(
        {
            "proposal_id": "proposal-1",
            "investigation_id": "investigation-1",
            "action": "CREATE_ISSUE",
            "payload": {"summary": "Payment API incident"},
            "evidence_references": ["investigation:investigation-1"],
        },
        config=config,
    )

    interrupt = pending["__interrupt__"][0]
    assert interrupt.value["proposal_id"] == "proposal-1"
    assert interrupt.value["payload"] == {"summary": "Payment API incident"}

    resumed = workflow.invoke(Command(resume="approve"), config=config)

    assert resumed["decision"] == "approve"


def test_created_jira_proposal_starts_a_durable_human_review() -> None:
    investigation_id = uuid4()
    proposal = JiraActionProposal(
        investigation_id=investigation_id,
        action=JiraProposalAction.CREATE_ISSUE,
        payload={
            "cloudId": "cloud-1",
            "projectKey": "OPS",
            "issueType": "Incident",
            "summary": "Payment API incident",
            "description": "Evidence-based draft.",
        },
    )

    class FakeInvestigationService:
        def get_investigation(self, requested_id):
            return object() if requested_id == investigation_id else None

    class FakeApprovalService:
        def propose_issue(self, requested_id, request):
            assert requested_id == investigation_id
            assert request.summary == "Payment API incident"
            return proposal

    class FakeReviewWorkflow:
        def __init__(self) -> None:
            self.calls: list[tuple[dict, dict]] = []

        def invoke(self, payload: dict, config: dict) -> dict:
            self.calls.append((payload, config))
            return {"__interrupt__": []}

    review_workflow = FakeReviewWorkflow()
    coroutine = propose_issue(
        investigation_id,
        JiraIssueCreateRequest(
            cloudId="cloud-1",
            projectKey="OPS",
            issueType="Incident",
            summary="Payment API incident",
            description="Evidence-based draft.",
        ),
        FakeInvestigationService(),
        FakeApprovalService(),
        review_workflow,
    )
    try:
        coroutine.send(None)
    except StopIteration as completed:
        created = completed.value
    else:
        raise AssertionError("The proposal route unexpectedly awaited I/O.")

    assert created == proposal
    assert review_workflow.calls == [
        (
            {
                "proposal_id": str(proposal.id),
                "investigation_id": str(investigation_id),
                "action": "CREATE_ISSUE",
                "payload": proposal.payload,
                "evidence_references": [f"investigation:{investigation_id}"],
            },
            {"configurable": {"thread_id": f"jira-proposal:{proposal.id}"}},
        )
    ]


def test_repeat_approval_does_not_resume_an_executed_human_review() -> None:
    proposal = JiraActionProposal(
        action=JiraProposalAction.CREATE_ISSUE,
        investigation_id=uuid4(),
        state=JiraProposalState.EXECUTED,
        payload={},
    )

    class FakeApprovalService:
        def get_proposal(self, requested_id):
            return proposal if requested_id == proposal.id else None

    class FakeReviewWorkflow:
        def invoke(self, payload, config):
            raise AssertionError("An executed proposal must not resume the HITL workflow.")

    with pytest.raises(HTTPException) as error:
        # The state guard runs before the route reaches its first await.  Driving the
        # coroutine once verifies that guard without starting an event loop solely
        # to receive this synchronous HTTP 409 response.
        approve_proposal(proposal.id, FakeApprovalService(), FakeReviewWorkflow()).send(None)

    assert error.value.status_code == 409

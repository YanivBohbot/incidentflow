from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incidentflow.agent.orchestration.jira_action_workflow import build_jira_action_workflow
from incidentflow.api.routes.jira import propose_issue
from incidentflow.domain.jira.models import (
    JiraActionProposal,
    JiraIssueCreateRequest,
    JiraProposalAction,
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

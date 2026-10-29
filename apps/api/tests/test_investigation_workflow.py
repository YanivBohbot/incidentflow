from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewType,
)


class FakeSupervisor:
    def __init__(self, report: InvestigationReport) -> None:
        self.report = report

    def invoke(self, payload: dict, config: dict) -> dict:
        assert payload["messages"][0]["content"] == "Payment API HTTP 500"
        assert config == {"recursion_limit": 14}
        return {"structured_response": self.report}


class UnavailableSupervisor:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, _payload: dict, config: dict) -> dict:
        assert config == {"recursion_limit": 14}
        self.calls += 1
        raise TimeoutError("provider timeout details must not reach the operator")


def test_invalid_request_finishes_without_building_the_supervisor() -> None:
    workflow = build_investigation_workflow()

    result = workflow.invoke({"incident_request": "   ", "incident_business_status": "open"})

    assert result["investigation_lifecycle"] == "failed"
    assert result["workflow_stage"] == "finished"
    assert result["report"] is None
    assert result["errors"] == ["incident_request must not be empty."]


def test_valid_request_runs_supervisor_and_finalizes_report() -> None:
    report = InvestigationReport(
        summary="Database pool exhaustion is suspected.",
        agents_consulted=[
            "it_operations_agent",
            "data_intelligence_agent",
            "knowledge_agent",
        ],
        evidence=[],
        hypotheses=["Connection pool exhaustion."],
        proposed_actions=["Request approval before mitigation."],
        limitations=["Sources are simulated."],
        confidence=0.8,
    )
    workflow = build_investigation_workflow(FakeSupervisor(report))

    result = workflow.invoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
    )

    assert result["investigation_lifecycle"] == "completed"
    assert result["workflow_stage"] == "finished"
    assert result["report"] == report
    assert result["errors"] == []


def test_human_review_interrupts_the_main_investigation_thread() -> None:
    report = InvestigationReport(
        summary="A Jira issue should be created for the confirmed production impact.",
        confidence=0.8,
        human_review=HumanReview(
            review_type=HumanReviewType.JIRA_WRITE,
            reason="Escalate the confirmed payment API outage.",
            evidence_references=["mongodb:event-17"],
            draft={"summary": "Payment API incident"},
        ),
    )
    workflow = build_investigation_workflow(
        FakeSupervisor(report),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "investigation:human-review"}}

    pending = workflow.invoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
        config=config,
    )

    assert pending["__interrupt__"][0].value["review_type"] == "JIRA_WRITE"
    assert pending["__interrupt__"][0].value["draft"] == {
        "summary": "Payment API incident"
    }

    resumed = workflow.invoke(
        Command(resume={"decision": "REJECT", "actor": "on-call-operator"}),
        config=config,
    )

    assert resumed["investigation_lifecycle"] == "completed"
    assert resumed["workflow_stage"] == "finished"


def test_exhausted_read_retry_becomes_a_safe_workflow_failure() -> None:
    supervisor = UnavailableSupervisor()
    workflow = build_investigation_workflow(supervisor)

    result = workflow.invoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
    )

    assert supervisor.calls == 2
    assert result["investigation_lifecycle"] == "failed"
    assert result["errors"] == ["One or more external sources could not be reached."]

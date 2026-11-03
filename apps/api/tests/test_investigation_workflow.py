import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incidentflow.agent.findings import InvestigationReport
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

    async def ainvoke(self, state: dict, *, config: dict) -> dict:
        assert state["messages"][0].content == "Payment API HTTP 500"
        assert config is not None
        return {"structured_response": self.report}


class UnavailableSupervisor:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _state: dict, *, config: dict) -> dict:
        self.calls += 1
        raise TimeoutError("provider timeout details must not reach the operator")


def test_invalid_request_finishes_without_building_the_supervisor() -> None:
    workflow = build_investigation_workflow(FakeSupervisor(InvestigationReport(summary="unused", confidence=0)))

    result = workflow.invoke({"incident_request": "   ", "incident_business_status": "open"})

    assert result["investigation_lifecycle"] == "failed"
    assert result["workflow_stage"] == "finished"
    assert result["report"] is None
    assert result["errors"] == ["incident_request must not be empty."]


@pytest.mark.anyio
async def test_valid_request_runs_supervisor_and_finalizes_report() -> None:
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

    result = await workflow.ainvoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
    )

    assert result["investigation_lifecycle"] == "completed"
    assert result["workflow_stage"] == "finished"
    assert result["report"] == report
    assert result["errors"] == []


@pytest.mark.anyio
async def test_human_review_interrupts_the_main_investigation_thread() -> None:
    report = InvestigationReport(
        summary="A Jira issue should be created for the confirmed production impact.",
        confidence=0.8,
        human_review=HumanReview(
        review_type=HumanReviewType.INSUFFICIENT_EVIDENCE,
        reason="More operational evidence is required before recommending a change.",
            evidence_references=["mongodb:event-17"],
            draft={"summary": "Payment API incident"},
        ),
    )
    workflow = build_investigation_workflow(FakeSupervisor(report), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "investigation:human-review"}}

    pending = await workflow.ainvoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
        config=config,
    )

    assert pending["__interrupt__"][0].value["review_type"] == "INSUFFICIENT_EVIDENCE"
    assert pending["__interrupt__"][0].value["draft"] == {
        "summary": "Payment API incident"
    }

    resumed = await workflow.ainvoke(
        Command(resume={"decision": "REJECT", "actor": "on-call-operator"}),
        config=config,
    )

    assert resumed["investigation_lifecycle"] == "completed"
    assert resumed["workflow_stage"] == "finished"


@pytest.mark.anyio
async def test_exhausted_read_retry_becomes_a_safe_workflow_failure() -> None:
    supervisor = UnavailableSupervisor()
    workflow = build_investigation_workflow(supervisor)

    result = await workflow.ainvoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
    )

    assert supervisor.calls == 2
    assert result["investigation_lifecycle"] == "failed"
    assert result["errors"] == ["One or more external sources could not be reached."]


class SupervisorStoppedWithoutReport:
    """Reproduce a supervisor run that ends before ToolStrategy produced a report."""

    async def ainvoke(self, _state: dict, *, config: dict) -> dict:
        return {"messages": [], "structured_response": None}


@pytest.mark.anyio
async def test_supervisor_without_report_fails_safely_instead_of_crashing() -> None:
    workflow = build_investigation_workflow(
        SupervisorStoppedWithoutReport(), checkpointer=InMemorySaver()
    )

    result = await workflow.ainvoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"},
        config={"configurable": {"thread_id": "no-report"}},
    )

    assert result["investigation_lifecycle"] == "failed"
    assert result["report"] is None
    assert result["errors"] == ["The Supervisor completed without a structured report."]


class RecordingSupervisor(FakeSupervisor):
    async def ainvoke(self, state: dict, *, config: dict) -> dict:
        self.config = config
        return {"structured_response": self.report}


@pytest.mark.anyio
async def test_supervisor_config_carries_the_original_operator_request() -> None:
    supervisor = RecordingSupervisor(InvestigationReport(summary="ok", confidence=0.5))
    workflow = build_investigation_workflow(supervisor)

    await workflow.ainvoke(
        {"incident_request": "Payment API HTTP 500", "incident_business_status": "open"}
    )

    assert supervisor.config["configurable"]["incident_request"] == "Payment API HTTP 500"

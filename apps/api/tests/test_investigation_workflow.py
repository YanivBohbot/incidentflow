from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)


class FakeSupervisor:
    def __init__(self, report: InvestigationReport) -> None:
        self.report = report

    def invoke(self, payload: dict, config: dict) -> dict:
        assert payload["messages"][0]["content"] == "Payment API HTTP 500"
        assert config == {"recursion_limit": 14}
        return {"structured_response": self.report}


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

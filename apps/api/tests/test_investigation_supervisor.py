from incidentflow.agent.agents_specialist.contracts import (
    InvestigationEvidence,
    InvestigationReport,
)
from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.agent.tools import specialist_delegation
from incidentflow.core.config import get_settings


class FakeFinding:
    def model_dump_json(self) -> str:
        return '{"summary":"specialist result"}'


class FakeSpecialistAgent:
    def invoke(self, payload: dict, config: dict) -> dict:
        assert payload["messages"][0]["content"] == "Payment API HTTP 500"
        assert config["recursion_limit"] == 6
        assert config["configurable"]["thread_id"].startswith("it-operations:")
        return {"structured_response": FakeFinding()}


def test_specialist_delegation_reports_jira_unavailability_without_simulation(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_MCP_ENABLED", "false")
    get_settings.cache_clear()

    result = specialist_delegation.ask_it_operations.invoke(
        {"incident_context": "Payment API HTTP 500"}
    )

    assert "Live Jira MCP is unavailable" in result
    assert "SIMULATED" not in result


def test_specialist_delegation_reports_mongodb_unavailability_without_simulation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MONGODB_MCP_ENABLED", "false")
    get_settings.cache_clear()

    result = specialist_delegation.ask_data_intelligence.invoke(
        {"incident_context": "Payment API HTTP 500"}
    )

    assert "Live MongoDB MCP is unavailable" in result
    assert "SIMULATED" not in result


def test_investigation_supervisor_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    supervisor = build_investigation_supervisor()

    assert supervisor.name == INVESTIGATION_SUPERVISOR.technical_name


def test_investigation_report_separates_evidence_and_actions() -> None:
    report = InvestigationReport(
        summary="The evidence points to database pool exhaustion.",
        agents_consulted=["it_operations_agent", "data_intelligence_agent"],
        evidence=[
            InvestigationEvidence(
                source="simulated_mongodb",
                detail="Connections reached the configured limit.",
                source_status="simulated",
            )
        ],
        hypotheses=["Connection pool exhaustion."],
        proposed_actions=["Request approval before changing traffic controls."],
        limitations=["Specialist sources are simulated."],
        confidence=0.8,
    )

    assert report.evidence[0].source_status == "simulated"
    assert report.proposed_actions == ["Request approval before changing traffic controls."]

from incidentflow.agent.agents_specialist.contracts import (
    InvestigationEvidence,
    ITOperationsFinding,
)
from incidentflow.agent.agents_specialist.it_operations import (
    build_it_operations_agent,
)
from incidentflow.agent.identities import IT_OPERATIONS_AGENT
from incidentflow.agent.tools.jira import search_incident_tickets
from incidentflow.core.config import get_settings


def test_simulated_ticket_search_is_explicitly_labeled() -> None:
    result = search_incident_tickets.invoke({"service_name": "Payment API"})

    assert result.startswith("SIMULATED DATA")
    assert "Payment API" in result


def test_it_operations_agent_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    agent = build_it_operations_agent()

    assert agent.name == IT_OPERATIONS_AGENT.technical_name
    assert IT_OPERATIONS_AGENT.display_name == "IT Operations Agent"


def test_it_operations_finding_separates_evidence_from_hypotheses() -> None:
    finding = ITOperationsFinding(
        summary="A related simulated ticket was found.",
        related_ticket_ids=["INC-104"],
        evidence=[
            InvestigationEvidence(
                source="simulated_jira",
                detail="INC-104 records Payment API HTTP 500 errors.",
                source_status="simulated",
            )
        ],
        hypotheses=["Database connection exhaustion could recur."],
        confidence=0.6,
    )

    assert finding.evidence[0].source_status == "simulated"
    assert finding.hypotheses == ["Database connection exhaustion could recur."]

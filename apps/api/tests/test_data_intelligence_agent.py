from incidentflow.agent.agents_specialist.contracts import (
    DataIntelligenceFinding,
    InvestigationEvidence,
)
from incidentflow.agent.agents_specialist.data_intelligence import (
    build_data_intelligence_agent,
)
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.agent.tools.operational_events import search_operational_events
from incidentflow.core.config import get_settings


def test_simulated_operational_events_are_explicitly_labeled() -> None:
    result = search_operational_events.invoke({"service_name": "Payment API"})

    assert result.startswith("SIMULATED DATA")
    assert "Payment API" in result


def test_data_intelligence_agent_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    agent = build_data_intelligence_agent()

    assert agent.name == DATA_INTELLIGENCE_AGENT.technical_name


def test_data_intelligence_finding_separates_events_from_causes() -> None:
    finding = DataIntelligenceFinding(
        summary="Pool timeouts occurred after the error-rate increase.",
        timeline=["09:05 UTC: HTTP 500 rate increased."],
        error_signatures=["database pool timeout"],
        evidence=[
            InvestigationEvidence(
                source="simulated_mongodb",
                detail="Active connections reached the configured limit.",
                source_status="simulated",
            )
        ],
        suspected_root_causes=["Connection pool exhaustion."],
        confidence=0.7,
    )

    assert finding.error_signatures == ["database pool timeout"]
    assert finding.suspected_root_causes == ["Connection pool exhaustion."]

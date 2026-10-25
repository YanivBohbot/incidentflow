from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import tool

from incidentflow.agent.agents_specialist.contracts import (
    DataIntelligenceFinding,
    InvestigationEvidence,
)
from incidentflow.agent.agents_specialist.data_intelligence import (
    build_data_intelligence_agent,
    build_data_intelligence_middleware,
)
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.core.config import get_settings


@tool("find")
def read_events() -> str:
    """Read test events."""
    return "event"


def test_data_intelligence_agent_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    agent = build_data_intelligence_agent([read_events])

    assert agent.name == DATA_INTELLIGENCE_AGENT.technical_name
    limiters = [
        middleware
        for middleware in build_data_intelligence_middleware()
        if isinstance(middleware, ToolCallLimitMiddleware)
    ]
    assert {(limiter.tool_name, limiter.run_limit) for limiter in limiters} == {
        ("collection-schema", 1),
        ("aggregate", 1),
        ("find", 1),
    }


def test_data_intelligence_finding_separates_events_from_causes() -> None:
    finding = DataIntelligenceFinding(
        summary="Pool timeouts occurred after the error-rate increase.",
        timeline=["09:05 UTC: HTTP 500 rate increased."],
        error_signatures=["database pool timeout"],
        evidence=[
            InvestigationEvidence(
                source="MongoDB",
                detail="Active connections reached the configured limit.",
                source_status="live",
            )
        ],
        suspected_root_causes=["Connection pool exhaustion."],
        confidence=0.7,
    )

    assert finding.error_signatures == ["database pool timeout"]
    assert finding.suspected_root_causes == ["Connection pool exhaustion."]

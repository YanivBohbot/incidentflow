from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.tools import tool

from incidentflow.agent.agents_specialist.data_intelligence import (
    build_data_intelligence_agent,
    build_data_intelligence_middleware,
)
from incidentflow.agent.findings import (
    DataIntelligenceFinding,
    InvestigationEvidence,
)
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.agent.tools.data_intelligence_tools import (
    _classify_dataset,
    _is_synthetic_dataset,
)
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
    assert {limiter.exit_behavior for limiter in limiters} == {"continue"}
    model_limiters = [
        middleware
        for middleware in build_data_intelligence_middleware()
        if isinstance(middleware, ModelCallLimitMiddleware)
    ]
    assert [(limiter.run_limit, limiter.exit_behavior) for limiter in model_limiters] == [
        (5, "end")
    ]


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


def test_synthetic_mongodb_events_are_never_presented_as_production_evidence() -> None:
    finding = DataIntelligenceFinding(
        summary="Connection pool exhaustion is suspected.",
        confidence=0.8,
    )

    classified = _classify_dataset(
        finding,
        is_synthetic=_is_synthetic_dataset(
            '[{"test_run":"incidentflow-mcp-test","message":"Synthetic test dataset"}]'
        ),
    )

    assert classified.data_classification == "synthetic"
    assert classified.limitations == [
        (
            "MongoDB returned a synthetic test dataset; it validates the investigation flow but "
            "cannot establish a production incident root cause."
        )
    ]


def test_ask_data_intelligence_runs_the_subagent_and_classifies_what_it_read(monkeypatch) -> None:
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from agent_fakes import scripted_model
    from langchain_core.tools import StructuredTool

    from incidentflow.agent.agents_specialist import data_intelligence as data_agent_module
    from incidentflow.agent.tools import data_intelligence_tools

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("MONGODB_MCP_ENABLED", "true")
    get_settings.cache_clear()
    calls: list[str] = []
    events = '[{"event_id": "SCN-SEARCH-001", "service": "search-api", "test_run": "demo"}]'

    def fake_tool(name: str, result: str) -> StructuredTool:
        async def run(**_arguments: object) -> str:
            calls.append(name)
            return result

        return StructuredTool.from_function(
            coroutine=run, name=name, description=name,
            args_schema={"type": "object", "properties": {}, "additionalProperties": True},
        )

    class FakeClient:
        def __init__(self, *_args: object) -> None:
            pass

        @asynccontextmanager
        async def read_tools(self):
            yield SimpleNamespace(read_tools=[
                fake_tool("collection-schema", '{"service": "string"}'),
                fake_tool("aggregate", events),
                fake_tool("find", "[]"),
            ])

    # The model does not say the data is synthetic; the application must still classify it.
    finding = {"summary": "Redis failover caused cache misses.", "confidence": 0.8}
    model = scripted_model([
        [("collection-schema", {"database": "d", "collection": "c"})],
        [("aggregate", {"database": "d", "collection": "c", "pipeline": []})],
        [("DataIntelligenceFinding", finding)],
    ])
    monkeypatch.setattr(data_intelligence_tools, "MongoDBMCPClient", FakeClient)
    monkeypatch.setattr(data_agent_module, "ChatOpenAI", lambda **_kwargs: model)

    result = DataIntelligenceFinding.model_validate_json(
        asyncio.run(
            data_intelligence_tools.ask_data_intelligence.ainvoke(
                {"incident_context": "search is slow", "service_name": "search-api"}
            )
        )
    )

    assert calls == ["collection-schema", "aggregate"]
    assert result.data_classification == "synthetic"
    assert result.summary == "Redis failover caused cache misses."

import asyncio

from langchain.agents.middleware import LLMToolSelectorMiddleware, ToolCallLimitMiddleware
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import (
    InvestigationEvidence,
    InvestigationReport,
)
from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.orchestration.supervisor import (
    build_investigation_supervisor,
    build_supervisor_middleware,
)
from incidentflow.agent.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
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

    result = asyncio.run(
        specialist_delegation.ask_it_operations.ainvoke(
            {"incident_context": "Payment API HTTP 500"}
        )
    )

    assert "Live Jira MCP is unavailable" in result
    assert "SIMULATED" not in result


def test_specialist_delegation_reports_mongodb_unavailability_without_simulation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MONGODB_MCP_ENABLED", "false")
    get_settings.cache_clear()

    result = asyncio.run(
        specialist_delegation.ask_data_intelligence.ainvoke(
            {"incident_context": "Payment API HTTP 500"}
        )
    )

    assert "Live MongoDB MCP is unavailable" in result
    assert "SIMULATED" not in result


def test_specialist_delegation_reports_github_unavailability_without_simulation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "false")
    get_settings.cache_clear()

    result = asyncio.run(
        specialist_delegation.ask_github.ainvoke(
            {"incident_context": "Payment API HTTP 500"}
        )
    )

    assert "Live GitHub MCP is unavailable" in result
    assert "SIMULATED" not in result


def test_specialist_tools_expose_stable_names_and_concise_descriptions() -> None:
    tools = {
        specialist_delegation.ask_it_operations.name: specialist_delegation.ask_it_operations,
        specialist_delegation.ask_data_intelligence.name: specialist_delegation.ask_data_intelligence,
        specialist_delegation.ask_knowledge.name: specialist_delegation.ask_knowledge,
        specialist_delegation.ask_github.name: specialist_delegation.ask_github,
    }

    assert set(tools) == {
        "ask_it_operations",
        "ask_data_intelligence",
        "ask_knowledge",
        "ask_github",
    }
    assert "Jira" in tools["ask_it_operations"].description
    assert "MongoDB" in tools["ask_data_intelligence"].description
    assert "documentation" in tools["ask_knowledge"].description
    assert "GitHub" in tools["ask_github"].description


def test_investigation_supervisor_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    supervisor = build_investigation_supervisor()

    assert supervisor.name == INVESTIGATION_SUPERVISOR.technical_name


def test_supervisor_allows_dynamic_selection_but_bounds_each_delegation() -> None:
    limiters = [
        middleware
        for middleware in build_supervisor_middleware()
        if isinstance(middleware, ToolCallLimitMiddleware)
    ]

    assert {(limiter.tool_name, limiter.run_limit) for limiter in limiters} == {
        ("ask_it_operations", 2),
        ("ask_data_intelligence", 2),
        ("ask_knowledge", 2),
        ("ask_github", 2),
    }
    selectors = [
        middleware
        for middleware in build_supervisor_middleware()
        if isinstance(middleware, LLMToolSelectorMiddleware)
    ]
    assert len(selectors) == 1
    assert selectors[0].max_tools == 4
    assert "exactly once" not in SUPERVISOR_SYSTEM_PROMPT
    assert "Select only the specialist delegations needed" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_selector_accepts_the_configured_chat_model() -> None:
    model = ChatOpenAI(model="gpt-4.1-mini", api_key="test-key")

    selector = next(
        middleware
        for middleware in build_supervisor_middleware(model)
        if isinstance(middleware, LLMToolSelectorMiddleware)
    )

    assert selector.model is model


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


def test_investigation_evidence_can_record_an_unavailable_source() -> None:
    evidence = InvestigationEvidence(
        source="ask_it_operations",
        detail="Live Jira MCP was unavailable during this investigation.",
        source_status="unavailable",
    )

    assert evidence.source_status == "unavailable"


def test_investigation_report_normalizes_unavailable_integration_evidence() -> None:
    report = InvestigationReport(
        summary="The GitHub source was unavailable.",
        agents_consulted=["github_agent"],
        evidence=[
            InvestigationEvidence(
                source="ask_github",
                detail="Live GitHub MCP was unavailable during this investigation.",
                source_status="live",
            )
        ],
        hypotheses=[],
        proposed_actions=[],
        limitations=["No GitHub evidence was collected."],
        confidence=0,
    )

    assert report.evidence[0].source_status == "unavailable"



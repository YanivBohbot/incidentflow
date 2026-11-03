from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.findings import (
    InvestigationEvidence,
    KnowledgeFinding,
)
from incidentflow.agent.identities import KNOWLEDGE_AGENT
from incidentflow.agent.tools.incident_response_guide_tools import (
    _is_evaluation_reference,
    build_knowledge_tools,
    search_simulated_incident_response_guides,
)
from incidentflow.core.config import get_settings


def test_simulated_incident_response_guides_are_explicitly_labeled() -> None:
    result = search_simulated_incident_response_guides.invoke({"query": "Payment API HTTP 500"})

    assert search_simulated_incident_response_guides.name == "search_incident_response_guides"
    assert result.startswith("SIMULATED DATA")
    assert "RUNBOOK-PAYMENTS-DB-001" in result


def test_evaluation_reference_is_not_treated_as_a_pinecone_document_id() -> None:
    assert _is_evaluation_reference("EVAL-CODE-003") is True
    assert _is_evaluation_reference("LOCAL-1A2B3C") is False


def test_knowledge_agent_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    agent = build_knowledge_agent()

    assert agent.name == KNOWLEDGE_AGENT.technical_name


def test_knowledge_agent_receives_runbook_and_confirmed_incident_tools(monkeypatch) -> None:
    class EnabledSettings:
        pinecone_enabled = True
        pinecone_resolved_incidents_enabled = True

    monkeypatch.setattr(
        "incidentflow.agent.tools.incident_response_guide_tools.get_settings",
        lambda: EnabledSettings(),
    )

    tools = build_knowledge_tools()

    assert {tool.name for tool in tools} >= {
        "search_incident_response_guides",
        "search_confirmed_incidents",
    }


def test_knowledge_finding_separates_documents_from_recommendations() -> None:
    finding = KnowledgeFinding(
        summary="The payment database-pool runbook is relevant.",
        relevant_documents=["RUNBOOK-PAYMENTS-DB-001"],
        evidence=[
            InvestigationEvidence(
                source="simulated_pinecone",
                detail="Verify database saturation and pool metrics.",
                source_status="simulated",
            )
        ],
        recommended_steps=["Review database saturation metrics."],
        limitations=["No live internal documents were queried."],
        confidence=0.7,
    )

    assert finding.relevant_documents == ["RUNBOOK-PAYMENTS-DB-001"]
    assert finding.recommended_steps == ["Review database saturation metrics."]


def test_ask_knowledge_runs_the_knowledge_subagent(monkeypatch) -> None:
    import asyncio

    from agent_fakes import scripted_model

    from incidentflow.agent.agents_specialist import knowledge as knowledge_agent_module
    from incidentflow.agent.findings import KnowledgeFinding
    from incidentflow.agent.tools.knowledge_tools import ask_knowledge

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("PINECONE_ENABLED", "false")  # simulated, offline retrieval tool
    get_settings.cache_clear()
    finding = {
        "summary": "Check the connection pool runbook.",
        "relevant_documents": ["runbook-pool"],
        "confidence": 0.6,
    }
    model = scripted_model([
        [("search_incident_response_guides", {"query": "connection pool exhaustion"})],
        [("KnowledgeFinding", finding)],
    ])
    monkeypatch.setattr(knowledge_agent_module, "ChatOpenAI", lambda **_kwargs: model)

    result = KnowledgeFinding.model_validate_json(
        asyncio.run(ask_knowledge.ainvoke({"incident_context": "checkout 503"}))
    )

    assert result.relevant_documents == ["runbook-pool"]
    assert result.confidence == 0.6

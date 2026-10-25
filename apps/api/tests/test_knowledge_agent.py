from incidentflow.agent.agents_specialist.contracts import (
    InvestigationEvidence,
    KnowledgeFinding,
)
from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.identities import KNOWLEDGE_AGENT
from incidentflow.agent.tools.runbooks import search_simulated_incident_response_guides
from incidentflow.core.config import get_settings


def test_simulated_incident_response_guides_are_explicitly_labeled() -> None:
    result = search_simulated_incident_response_guides.invoke({"query": "Payment API HTTP 500"})

    assert search_simulated_incident_response_guides.name == "search_incident_response_guides"
    assert result.startswith("SIMULATED DATA")
    assert "RUNBOOK-PAYMENTS-DB-001" in result


def test_knowledge_agent_builds_without_a_model_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    agent = build_knowledge_agent()

    assert agent.name == KNOWLEDGE_AGENT.technical_name


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

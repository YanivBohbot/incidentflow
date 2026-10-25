from langchain_core.tools import tool

from incidentflow.agent.agents_specialist.contracts import (
    InvestigationEvidence,
    ITOperationsFinding,
)
from incidentflow.agent.agents_specialist.it_operations import (
    build_it_operations_agent,
)
from incidentflow.agent.identities import IT_OPERATIONS_AGENT
from incidentflow.core.config import get_settings


@tool("searchJiraIssuesUsingJql")
def search_jira_issues_using_jql(jql: str) -> str:
    """Search live Jira issues using JQL."""
    return f"Fixture Jira result for {jql}"


def test_it_operations_agent_builds_with_injected_jira_tools(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    agent = build_it_operations_agent([search_jira_issues_using_jql])

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

"""Create idempotent synthetic Jira tickets for IncidentFlow evaluation scenarios."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings

PROJECT_KEY = "SAM1"
LABELS = ["incidentflow-evaluation", "synthetic-data"]


@dataclass(frozen=True)
class JiraEvaluationScenario:
    """One synthetic ticket that correlates with MongoDB, RAG, or GitHub evidence."""

    scenario_id: str
    summary: str
    correlation_id: str
    description: str


SCENARIOS = (
    JiraEvaluationScenario(
        scenario_id="EVAL-PAY-001",
        summary="[IncidentFlow evaluation] Payment API HTTP 500 connection pool exhaustion",
        correlation_id="incidentflow-payment-test-001",
        description=(
            "Synthetic IncidentFlow evaluation ticket.\n\n"
            "Correlation ID: incidentflow-payment-test-001\n"
            "Service: payment-api\n"
            "Expected evidence: HTTP 500 increase, MongoDB pool timeouts, and active connections "
            "reaching the configured limit.\n"
            "Use this ticket only to evaluate read-only investigation routing and human-approved Jira writes."
        ),
    ),
    JiraEvaluationScenario(
        scenario_id="EVAL-AUTH-002",
        summary="[IncidentFlow evaluation] Identity API JWT key rotation authentication failures",
        correlation_id="incidentflow-auth-test-002",
        description=(
            "Synthetic IncidentFlow evaluation ticket.\n\n"
            "Correlation ID: incidentflow-auth-test-002\n"
            "Service: identity-api\n"
            "Expected evidence: JWT signature failures, HTTP 401 increase, and verification-key cache refresh.\n"
            "Use this ticket only to evaluate Jira, MongoDB, and knowledge-base investigation routing."
        ),
    ),
    JiraEvaluationScenario(
        scenario_id="EVAL-CODE-003",
        summary="[IncidentFlow evaluation] Checkout API missing payment provider configuration",
        correlation_id="incidentflow-checkout-test-003",
        description=(
            "Synthetic IncidentFlow evaluation ticket.\n\n"
            "Correlation ID: incidentflow-checkout-test-003\n"
            "Service: checkout-api\n"
            "Expected evidence: deployment followed by missing payment-provider configuration and HTTP 500 errors.\n"
            "Related GitHub fixture: YanivBohbot/incidentflow-evaluation-fixtures PR #1.\n"
            "Use this ticket only to evaluate Jira and GitHub change-correlation behavior."
        ),
    ),
)


async def main() -> None:
    """Create each scenario only when an existing Jira search cannot find it."""
    settings = get_settings()
    if not settings.jira_mcp_enabled or not settings.jira_mcp_write_enabled:
        raise RuntimeError(
            "Set JIRA_MCP_ENABLED=true and JIRA_MCP_WRITE_ENABLED=true before seeding Jira data."
        )

    async with JiraMCPClient(settings.jira_mcp_url).ticket_tools() as tool_set:
        cloud_id = _first_cloud_id(
            await tool_set.get("getAccessibleAtlassianResources").ainvoke({})
        )
        for scenario in SCENARIOS:
            existing_key = _first_issue_key(
                await tool_set.get("searchJiraIssuesUsingJql").ainvoke(
                    {
                        "cloudId": cloud_id,
                        "jql": (
                            f'project = {PROJECT_KEY} AND labels = "incidentflow-evaluation" '
                            f'AND summary ~ "{scenario.scenario_id}"'
                        ),
                        "maxResults": 1,
                    }
                )
            )
            if existing_key:
                print(f"{scenario.scenario_id}: existing Jira issue {existing_key}")
                continue

            created = await tool_set.get("createJiraIssue").ainvoke(
                {
                    "cloudId": cloud_id,
                    "projectKey": PROJECT_KEY,
                    "issueType": "Task",
                    "summary": scenario.summary,
                    "description": scenario.description,
                    "additional_fields": {"labels": [*LABELS, scenario.scenario_id.lower()]},
                }
            )
            created_key = _first_issue_key(created)
            if created_key is None:
                raise RuntimeError(f"Jira did not return an issue key for {scenario.scenario_id}.")
            print(f"{scenario.scenario_id}: created Jira issue {created_key}")


def _first_cloud_id(result: Any) -> str:
    """Extract the first accessible Jira Cloud resource identifier."""
    resources = _tool_payload(result)["data"]["resources"]
    return resources[0]["cloudId"]


def _first_issue_key(result: Any) -> str | None:
    """Find the first Jira issue key in an MCP response without printing ticket content."""
    return _find_key(_tool_payload(result))


def _tool_payload(result: Any) -> dict[str, Any]:
    """Decode the JSON text envelope returned by the Jira MCP server."""
    return json.loads(result[0]["text"])


def _find_key(value: Any) -> str | None:
    """Traverse a Jira response until an issue key is found."""
    if isinstance(value, dict):
        key = value.get("key")
        if isinstance(key, str) and key:
            return key
        for nested_value in value.values():
            found_key = _find_key(nested_value)
            if found_key:
                return found_key
    if isinstance(value, list):
        for nested_value in value:
            found_key = _find_key(nested_value)
            if found_key:
                return found_key
    return None


if __name__ == "__main__":
    asyncio.run(main())

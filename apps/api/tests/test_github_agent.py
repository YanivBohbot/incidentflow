from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.tools import tool

from incidentflow.agent.agents_specialist.contracts import (
    GitHubFinding,
    InvestigationEvidence,
)
from incidentflow.agent.agents_specialist.github import (
    build_github_agent,
    build_github_middleware,
    validate_github_repository_arguments,
)
from incidentflow.agent.identities import GITHUB_AGENT
from incidentflow.agent.mcp_clients.github import GitHubMCPClient
from incidentflow.core.config import get_settings


@tool("list_commits")
def list_commits() -> str:
    """Read commits."""
    return "commit"


def test_github_agent_builds_with_injected_read_tools(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("GITHUB_MCP_REPOSITORIES", "acme/payment-api,acme/customer-portal")
    get_settings.cache_clear()

    agent = build_github_agent([list_commits])

    assert agent.name == GITHUB_AGENT.technical_name
    limiters = [
        middleware
        for middleware in build_github_middleware(
            ("acme/payment-api", "acme/customer-portal")
        )
        if isinstance(middleware, ToolCallLimitMiddleware)
    ]
    assert {(limiter.tool_name, limiter.run_limit) for limiter in limiters} == {
        (None, 4),
        ("list_commits", 1),
        ("list_pull_requests", 1),
        ("pull_request_read", 2),
        ("search_code", 1),
    }
    assert {limiter.exit_behavior for limiter in limiters} == {"continue"}
    model_limiter = next(
        middleware
        for middleware in build_github_middleware(
            ("acme/payment-api", "acme/customer-portal")
        )
        if isinstance(middleware, ModelCallLimitMiddleware)
    )
    assert model_limiter.run_limit == 4
    assert model_limiter.exit_behavior == "end"
    assert get_settings().github_mcp_allowed_repositories == (
        "acme/payment-api",
        "acme/customer-portal",
    )


def test_github_mcp_client_supports_local_stdio_transport() -> None:
    client = GitHubMCPClient(command="docker", command_args=("run", "-i"))

    assert client.command == "docker"
    assert client.command_args == ("run", "-i")


def test_github_finding_separates_change_evidence_from_hypotheses() -> None:
    finding = GitHubFinding(
        summary="A database pool configuration change was merged before the incident window.",
        repository="acme/payment-api",
        related_pull_requests=["#184"],
        related_commits=["f00ba4"],
        evidence=[
            InvestigationEvidence(
                source="GitHub",
                detail="PR #184 changed the payment connection-pool settings.",
                source_status="live",
            )
        ],
        hypotheses=["The pool configuration change may have contributed to request failures."],
        limitations=[],
        confidence=0.6,
    )

    assert finding.related_pull_requests == ["#184"]
    assert finding.hypotheses == [
        "The pool configuration change may have contributed to request failures."
    ]


def test_github_repository_allowlist_covers_owner_repo_and_code_search() -> None:
    allowed = ("acme/payment-api", "acme/customer-portal")

    assert validate_github_repository_arguments(
        "list_commits", {"owner": "acme", "repo": "payment-api"}, allowed
    ) is None
    assert validate_github_repository_arguments(
        "list_pull_requests", {"owner": "other", "repo": "private-repo"}, allowed
    ) == "GitHub tool requested a repository outside the allowlist."
    assert validate_github_repository_arguments(
        "search_code", {"query": "INC-204 repo:acme/customer-portal"}, allowed
    ) is None
    assert validate_github_repository_arguments(
        "search_code", {"query": "INC-204"}, allowed
    ) == "GitHub code search requires a repo:owner/repository qualifier from the allowlist."

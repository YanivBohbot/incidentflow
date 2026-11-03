from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.tools import tool

from incidentflow.agent.agents_specialist.github import (
    build_github_agent,
    build_github_middleware,
    validate_github_repository_arguments,
)
from incidentflow.agent.findings import (
    GitHubFinding,
    InvestigationEvidence,
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
    assert model_limiter.run_limit == 6
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


def test_ask_github_runs_the_github_subagent_inside_the_repository_allowlist(monkeypatch) -> None:
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from agent_fakes import scripted_model
    from langchain_core.tools import StructuredTool

    from incidentflow.agent.agents_specialist import github as github_agent_module
    from incidentflow.agent.tools import github_tools

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "true")
    monkeypatch.setenv("GITHUB_MCP_REPOSITORIES", "acme/payment-api")
    monkeypatch.setenv("GITHUB_MCP_BRANCH", "demo/incident-scenarios")
    get_settings.cache_clear()
    calls: list[tuple[str, dict]] = []

    def fake_tool(name: str) -> StructuredTool:
        async def run(**arguments: object) -> str:
            calls.append((name, arguments))
            return "x" * 9000  # larger than the truncation budget

        return StructuredTool.from_function(
            coroutine=run, name=name, description=name,
            args_schema={"type": "object", "properties": {}, "additionalProperties": True},
        )

    class FakeClient:
        @asynccontextmanager
        async def read_tools(self):
            yield SimpleNamespace(read_tools=[fake_tool("list_commits"), fake_tool("list_pull_requests")])

    finding = {
        "summary": "A pool change was merged before the incident.",
        "repository": "acme/payment-api",
        "related_commits": ["f00ba4"],
        "confidence": 0.6,
    }
    model = scripted_model([
        [("list_commits", {"owner": "acme", "repo": "payment-api"}),
         ("list_pull_requests", {"owner": "other", "repo": "secret"})],
        [("GitHubFinding", finding)],
    ])
    monkeypatch.setattr(github_tools, "_create_github_mcp_client", lambda: FakeClient())
    monkeypatch.setattr(github_agent_module, "ChatOpenAI", lambda **_kwargs: model)

    result = GitHubFinding.model_validate_json(
        asyncio.run(github_tools.ask_github.ainvoke({"incident_context": "HTTP 500"}))
    )

    assert result.related_commits == ["f00ba4"]
    # The out-of-allowlist read was blocked before reaching the GitHub MCP server, and the
    # allowed read was pointed at the configured branch by the application.
    assert calls == [
        ("list_commits", {"owner": "acme", "repo": "payment-api", "sha": "demo/incident-scenarios"})
    ]


def test_a_blocked_extra_call_produces_exactly_one_tool_message(monkeypatch) -> None:
    """Regression: two limiters blocking one call sent duplicate ToolMessages (OpenAI 400)."""
    import asyncio

    from agent_fakes import scripted_model
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import StructuredTool

    from incidentflow.agent.agents_specialist import github as github_agent_module

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("GITHUB_MCP_REPOSITORIES", "acme/payment-api")
    get_settings.cache_clear()

    async def run(**_arguments: object) -> str:
        return "[]"

    commits = StructuredTool.from_function(
        coroutine=run, name="list_commits", description="commits",
        args_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    read = ("list_commits", {"owner": "acme", "repo": "payment-api"})
    finding = {"summary": "No change.", "repository": "acme/payment-api", "confidence": 0.1}
    model = scripted_model([[read] * 5, [("GitHubFinding", finding)]])  # 5 calls in one turn
    monkeypatch.setattr(github_agent_module, "ChatOpenAI", lambda **_kwargs: model)

    result = asyncio.run(
        build_github_agent([commits]).ainvoke(
            {"messages": [{"role": "user", "content": "HTTP 500"}]}, {"recursion_limit": 60}
        )
    )

    tool_call_ids = [m.tool_call_id for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_call_ids) == len(set(tool_call_ids))
    assert result["structured_response"].summary == "No change."


def test_branch_defaults_target_the_configured_branch_without_overriding_the_model() -> None:
    from incidentflow.agent.agents_specialist.github import with_branch_defaults

    branch = "demo/incident-scenarios"
    assert with_branch_defaults("list_commits", {"owner": "a"}, branch)["sha"] == branch
    assert with_branch_defaults("list_commits", {"sha": "main"}, branch)["sha"] == "main"
    assert with_branch_defaults("list_pull_requests", {}, branch) == {"base": branch, "state": "all"}
    assert with_branch_defaults("list_commits", {"owner": "a"}, None) == {"owner": "a"}

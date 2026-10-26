"""Deterministic checks for the Supervisor's delegated-tool behavior."""

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SupervisorRoutingScenario:
    """One user request and the specialist delegations it should require."""

    name: str
    request: str
    expected_tools: frozenset[str]


@dataclass(frozen=True)
class RoutingAssessment:
    """The actual tool calls made by one Supervisor run."""

    delegated_tools: tuple[str, ...]
    expected_tools: frozenset[str]
    unexpected_tools: frozenset[str]
    missing_tools: frozenset[str]
    excessively_repeated_tools: frozenset[str]

    @property
    def passed(self) -> bool:
        return not (
            self.unexpected_tools or self.missing_tools or self.excessively_repeated_tools
        )


SUPERVISOR_ROUTING_SCENARIOS = (
    SupervisorRoutingScenario(
        name="knowledge_only",
        request=(
            "Retrieve the documented procedure for investigating MongoDB connection pool exhaustion. "
            "Do not inspect Jira, live operational events, or source-control changes."
        ),
        expected_tools=frozenset({"ask_knowledge"}),
    ),
    SupervisorRoutingScenario(
        name="mongodb_only",
        request=(
            "Inspect live MongoDB operational events for Payment API HTTP 500 errors. "
            "Do not inspect Jira, documentation, or source-control changes."
        ),
        expected_tools=frozenset({"ask_data_intelligence"}),
    ),
    SupervisorRoutingScenario(
        name="jira_only",
        request=(
            "Read the Jira incident INC-204 and summarize its priority, status, and comments. "
            "Do not inspect operational events, documentation, or source-control changes."
        ),
        expected_tools=frozenset({"ask_it_operations"}),
    ),
    SupervisorRoutingScenario(
        name="github_only",
        request=(
            "Review recent commits and pull requests for the Payment API repository. "
            "Do not inspect Jira, operational events, or documentation."
        ),
        expected_tools=frozenset({"ask_github"}),
    ),
    SupervisorRoutingScenario(
        name="full_investigation",
        request=(
            "Investigate Jira incident INC-204 end to end: read its ticket context, inspect the "
            "corresponding MongoDB events, find similar response procedures, and review relevant "
            "recent GitHub changes."
        ),
        expected_tools=frozenset(
            {
                "ask_it_operations",
                "ask_data_intelligence",
                "ask_knowledge",
                "ask_github",
            }
        ),
    ),
)


def assess_delegations(
    expected_tools: frozenset[str], delegated_tools: Iterable[str], max_calls_per_tool: int = 2
) -> RoutingAssessment:
    """Assess whether a run stayed within the Supervisor's delegation policy.

    A specialist must be called at least once when expected. One evidence-driven
    follow-up is permitted, matching the production per-tool call limit of two.
    """
    if max_calls_per_tool < 1:
        raise ValueError("max_calls_per_tool must be at least 1.")
    tool_names = tuple(delegated_tools)
    counts = Counter(tool_names)
    actual_tools = frozenset(counts)
    return RoutingAssessment(
        delegated_tools=tool_names,
        expected_tools=expected_tools,
        unexpected_tools=actual_tools - expected_tools,
        missing_tools=expected_tools - actual_tools,
        excessively_repeated_tools=frozenset(
            name for name, count in counts.items() if count > max_calls_per_tool
        ),
    )

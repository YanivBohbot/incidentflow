"""Deterministic checks for the Supervisor's delegated-tool behavior."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from evaluation.scenarios.catalog import TRAJECTORY_SCENARIOS


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
        return not (self.unexpected_tools or self.missing_tools or self.excessively_repeated_tools)


_ROUTING_SCENARIO_NAMES = (
    "knowledge_only",
    "mongodb_only",
    "jira_only",
    "github_only",
    "cloudwatch_only",
    "full_investigation",
)

# Derived from the trajectory catalog so requests and expectations have one source of truth.
SUPERVISOR_ROUTING_SCENARIOS = tuple(
    SupervisorRoutingScenario(
        name=scenario.name,
        request=scenario.incident_request,
        expected_tools=scenario.required_specialists,
    )
    for name in _ROUTING_SCENARIO_NAMES
    for scenario in TRAJECTORY_SCENARIOS
    if scenario.name == name
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

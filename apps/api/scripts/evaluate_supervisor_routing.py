"""Evaluate dynamic Supervisor routing with safe local specialist stubs."""

import argparse
import json
from collections import Counter
from collections.abc import Iterable

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from incidentflow.agent.evaluation.supervisor_routing import (
    SUPERVISOR_ROUTING_SCENARIOS,
    SupervisorRoutingScenario,
    assess_delegations,
)
from incidentflow.agent.orchestration.supervisor import build_supervisor_middleware
from incidentflow.core.config import get_settings

TOOL_EXECUTIONS: list[str] = []


@tool
def ask_it_operations(incident_context: str) -> str:
    """Read Jira incident tickets, priority, status, and comments for the supplied context."""
    TOOL_EXECUTIONS.append("ask_it_operations")
    return '{"source":"routing-evaluation","specialist":"jira"}'


@tool
def ask_data_intelligence(incident_context: str) -> str:
    """Read MongoDB operational events, logs, error signatures, and technical timelines."""
    TOOL_EXECUTIONS.append("ask_data_intelligence")
    return '{"source":"routing-evaluation","specialist":"mongodb"}'


@tool
def ask_knowledge(incident_context: str) -> str:
    """Read incident response procedures and similar documented incidents from the knowledge base."""
    TOOL_EXECUTIONS.append("ask_knowledge")
    return '{"source":"routing-evaluation","specialist":"knowledge"}'


@tool
def ask_github(incident_context: str) -> str:
    """Read recent GitHub commits, pull requests, and source-code changes for the incident."""
    TOOL_EXECUTIONS.append("ask_github")
    return '{"source":"routing-evaluation","specialist":"github"}'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of repetitions for each scenario. Default: 1.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print one compact summary instead of one JSON line per run.",
    )
    return parser.parse_args()


def _delegated_tools(messages: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        tool_call["name"]
        for message in messages
        for tool_call in getattr(message, "tool_calls", [])
        if tool_call["name"].startswith("ask_")
    )


def _build_evaluation_supervisor():
    settings = get_settings()
    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=settings.openai_timeout_seconds,
    )
    return create_agent(
        model=model,
        tools=[ask_it_operations, ask_data_intelligence, ask_knowledge, ask_github],
        name="supervisor_routing_evaluation",
        system_prompt=(
            "You are evaluating dynamic specialist routing. Use every available specialist tool "
            "exactly once, and use no unavailable specialist. Do not infer evidence yourself. "
            "After tool results, return a concise acknowledgement."
        ),
        middleware=build_supervisor_middleware(model),
    )


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise ValueError("--runs must be at least 1.")

    supervisor = _build_evaluation_supervisor()
    all_passed = True
    records: list[dict[str, object]] = []
    for scenario in SUPERVISOR_ROUTING_SCENARIOS:
        for run_number in range(1, args.runs + 1):
            TOOL_EXECUTIONS.clear()
            result = supervisor.invoke(
                {"messages": [{"role": "user", "content": scenario.request}]},
                config={
                    "recursion_limit": 12,
                    "configurable": {"thread_id": f"routing-evaluation:{scenario.name}:{run_number}"},
                },
            )
            assessment = assess_delegations(
                scenario.expected_tools,
                TOOL_EXECUTIONS,
            )
            all_passed = all_passed and assessment.passed
            record = {
                "scenario": scenario.name,
                "run": run_number,
                "passed": assessment.passed,
                "expected_tools": sorted(assessment.expected_tools),
                "executed_tools": list(assessment.delegated_tools),
                "requested_tools": list(_delegated_tools(result["messages"])),
                "missing_tools": sorted(assessment.missing_tools),
                "unexpected_tools": sorted(assessment.unexpected_tools),
                        "excessively_repeated_tools": sorted(
                            assessment.excessively_repeated_tools
                        ),
            }
            records.append(record)
            if not args.summary:
                print(json.dumps(record))

    if args.summary:
        scenarios: dict[str, dict[str, object]] = {}
        for scenario in SUPERVISOR_ROUTING_SCENARIOS:
            scenario_records = [record for record in records if record["scenario"] == scenario.name]
            max_requested_calls = max(
                (
                    max(Counter(record["requested_tools"]).values(), default=0)
                    for record in scenario_records
                ),
                default=0,
            )
            scenarios[scenario.name] = {
                "runs": len(scenario_records),
                "passed_runs": sum(bool(record["passed"]) for record in scenario_records),
                "expected_tools": sorted(scenario.expected_tools),
                "max_repeated_request_attempts": max_requested_calls,
                "max_executed_calls_allowed": 2,
            }
        print(json.dumps({"passed": all_passed, "scenarios": scenarios}, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

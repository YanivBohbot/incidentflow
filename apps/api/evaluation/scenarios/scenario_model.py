"""Scenario dataclass, frozen-finding builders and dataset example builders."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from evaluation.harness.fixtures import FINDING_MODELS
from incidentflow.agent.findings import InvestigationEvidence

ExampleSpec = dict[str, Any]

ALL_SPECIALISTS: frozenset[str] = frozenset(FINDING_MODELS)

# Names the supervisor LLM tends to write as an evidence source, per delegation tool.
SOURCE_ALIASES: Mapping[str, tuple[str, ...]] = {
    "ask_it_operations": ("Jira",),
    "ask_data_intelligence": ("MongoDB",),
    "ask_knowledge": ("Knowledge base", "Knowledge", "Pinecone"),
    "ask_github": ("GitHub",),
    "ask_cloudwatch": ("CloudWatch",),
}


@dataclass(frozen=True)
class EvaluationScenario:
    """One incident request, the specialist findings it is replayed with, and its references."""

    name: str
    incident_request: str
    frozen_findings: Mapping[str, str]
    required_specialists: frozenset[str]
    forbidden_specialists: frozenset[str]
    key_facts: tuple[str, ...]
    expected_root_cause: str | None
    unsafe_actions: tuple[str, ...]
    source_tools: Mapping[str, str]


def finding(tool: str, **fields: Any) -> str:
    """Build a validated frozen finding of the tool's model and return its JSON."""
    return FINDING_MODELS[tool](**fields).model_dump_json()


def evidence(source: str, detail: str) -> InvestigationEvidence:
    return InvestigationEvidence(source=source, detail=detail, source_status="simulated")


def source_tools_for(findings: Mapping[str, str]) -> dict[str, str]:
    """Map every evidence source string a report may cite to its delegation tool."""
    mapping: dict[str, str] = {}
    for tool, raw in findings.items():
        mapping[tool] = tool
        mapping.update({alias: tool for alias in SOURCE_ALIASES[tool]})
        mapping.update({item["source"]: tool for item in json.loads(raw).get("evidence", [])})
    # Tools without a frozen finding return an "unavailable" placeholder that reports still cite.
    for tool, aliases in SOURCE_ALIASES.items():
        if tool not in findings:
            mapping[tool] = tool
            mapping.update({alias: tool for alias in aliases})
    return mapping


def scenario(
    name: str,
    incident_request: str,
    *,
    findings: Mapping[str, str],
    required: Iterable[str],
    forbidden: Iterable[str] = (),
    key_facts: Iterable[str] = (),
    expected_root_cause: str | None = None,
    unsafe_actions: Iterable[str] = (),
) -> EvaluationScenario:
    return EvaluationScenario(
        name=name,
        incident_request=incident_request,
        frozen_findings=dict(findings),
        required_specialists=frozenset(required),
        forbidden_specialists=frozenset(forbidden),
        key_facts=tuple(key_facts),
        expected_root_cause=expected_root_cause,
        unsafe_actions=tuple(unsafe_actions),
        source_tools=source_tools_for(findings),
    )


def _base_example(s: EvaluationScenario) -> ExampleSpec:
    return {
        "inputs": {"incident_request": s.incident_request, "scenario": s.name},
        "metadata": {"scenario": s.name},
    }


def trajectory_example(s: EvaluationScenario) -> ExampleSpec:
    return {
        **_base_example(s),
        "outputs": {
            "required_specialists": sorted(s.required_specialists),
            "forbidden_specialists": sorted(s.forbidden_specialists),
            "key_facts": sorted(s.key_facts),
        },
    }


def report_example(s: EvaluationScenario) -> ExampleSpec:
    return {
        **_base_example(s),
        "outputs": {
            "required_specialists": sorted(s.required_specialists),
            "expected_root_cause": s.expected_root_cause,
            "unsafe_actions": sorted(s.unsafe_actions),
            "unavailable_sources": sorted(ALL_SPECIALISTS - set(s.frozen_findings)),
            "source_tools": dict(sorted(s.source_tools.items())),
            "frozen_findings": dict(sorted(s.frozen_findings.items())),
            "key_facts": sorted(s.key_facts),
        },
    }

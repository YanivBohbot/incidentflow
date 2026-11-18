"""Fixture delegation tools: frozen specialist findings in place of live integrations."""

from collections.abc import Mapping
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from incidentflow.agent.findings import (
    CloudWatchFinding,
    DataIntelligenceFinding,
    GitHubFinding,
    ITOperationsFinding,
    KnowledgeFinding,
)
from incidentflow.agent.orchestration.supervisor import DELEGATION_TOOLS

CallLog = list[dict[str, Any]]

FINDING_MODELS: Mapping[str, type[BaseModel]] = {
    "ask_it_operations": ITOperationsFinding,
    "ask_data_intelligence": DataIntelligenceFinding,
    "ask_knowledge": KnowledgeFinding,
    "ask_github": GitHubFinding,
    "ask_cloudwatch": CloudWatchFinding,
}

_SOURCE_NAMES = {
    "ask_it_operations": "Jira",
    "ask_data_intelligence": "MongoDB",
    "ask_knowledge": "Knowledge",
    "ask_github": "GitHub",
    "ask_cloudwatch": "CloudWatch",
}

# Required fields beyond summary/confidence, per model.
_REQUIRED_EXTRAS: dict[str, dict[str, Any]] = {
    "ask_github": {"repository": "unavailable"},
    "ask_cloudwatch": {"investigation_status": "unavailable"},
}


def unavailable_finding_json(tool_name: str) -> str:
    """Return a zero-confidence finding of the tool's model for a source with no fixture."""
    # Same wording as the production tools, so InvestigationReport's safety net that marks
    # outage evidence "unavailable" behaves in evaluations exactly as it does in production.
    if tool_name == "ask_knowledge":
        summary = "Knowledge retrieval was unavailable during this investigation."
    else:
        summary = f"Live {_SOURCE_NAMES[tool_name]} MCP was unavailable during this investigation."
    model = FINDING_MODELS[tool_name]
    return model(
        summary=summary, confidence=0, **_REQUIRED_EXTRAS.get(tool_name, {})
    ).model_dump_json()


def fixture_delegations(findings: Mapping[str, str], call_log: CallLog) -> list[BaseTool]:
    """Build one stub per real delegation tool that returns its frozen finding JSON."""

    def build(real: BaseTool) -> BaseTool:
        async def stub(**kwargs: Any) -> str:
            call_log.append({"tool": real.name, "args": kwargs})
            return findings.get(real.name) or unavailable_finding_json(real.name)

        return StructuredTool.from_function(
            coroutine=stub,
            name=real.name,
            description=real.description,
            args_schema=real.args_schema,
        )

    return [build(real) for real in DELEGATION_TOOLS]

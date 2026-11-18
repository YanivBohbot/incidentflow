"""Record an investigation run's trajectory: delegations, nested tool calls, node path, interrupts."""

import json
from typing import Any
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackHandler

from evaluation.harness.fixtures import CallLog
from incidentflow.agent.orchestration.supervisor import DELEGATION_TOOLS

DELEGATION_NAMES = frozenset(tool.name for tool in DELEGATION_TOOLS)


class TrajectoryRecorder(AsyncCallbackHandler):
    """Collect tool calls from every run under a workflow, including nested specialist calls."""

    def __init__(self) -> None:
        # run_id -> (parent_run_id, tool name when the run is a tool)
        self._runs: dict[UUID, tuple[UUID | None, str | None]] = {}
        self._calls: list[tuple[UUID, str, dict[str, Any]]] = []

    def _register(self, run_id: UUID, parent_run_id: UUID | None, tool: str | None = None) -> None:
        self._runs[run_id] = (parent_run_id, tool)

    async def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **_: Any,
    ) -> None:
        self._register(run_id, parent_run_id)

    async def on_chat_model_start(
        self,
        serialized: Any,
        messages: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **_: Any,
    ) -> None:
        self._register(run_id, parent_run_id)

    async def on_llm_start(
        self,
        serialized: Any,
        prompts: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **_: Any,
    ) -> None:
        self._register(run_id, parent_run_id)

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        name: str | None = None,
        **_: Any,
    ) -> None:
        tool = name or (serialized or {}).get("name") or "unknown"
        self._register(run_id, parent_run_id, tool)
        self._calls.append((run_id, tool, dict(inputs or {})))

    def _agent_of(self, run_id: UUID) -> str | None:
        seen: set[UUID] = set()
        current = self._runs.get(run_id, (None, None))[0]
        while current is not None and current not in seen:
            seen.add(current)
            parent, tool = self._runs.get(current, (None, None))
            if tool in DELEGATION_NAMES:
                return tool
            current = parent
        return None

    @property
    def nested_tool_calls(self) -> list[dict[str, Any]]:
        return [
            {"agent": self._agent_of(run_id), "tool": tool, "args": args}
            for run_id, tool, args in self._calls
            if tool not in DELEGATION_NAMES
        ]

    @property
    def delegation_calls(self) -> list[dict[str, Any]]:
        """Top-level specialist delegations in start order, shaped like the fixture call log."""
        return [
            {"tool": tool, "args": _json_safe(args)}
            for run_id, tool, args in self._calls
            if tool in DELEGATION_NAMES and self._agent_of(run_id) is None
        ]

    def as_outputs(self) -> dict[str, Any]:
        return {"nested_tool_calls": self.nested_tool_calls}


def _json_safe(args: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in args.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        safe[key] = value
    return safe


def _classify_interrupt(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and "action_requests" in value:
        requests = value["action_requests"] or []
        first = requests[0] if requests else {}
        tool = first.get("name") if isinstance(first, dict) else None
        return {"kind": "jira_write", "tool": tool}
    return {"kind": "report_review", "tool": None}


def _report_json(report: Any) -> dict[str, Any] | None:
    if hasattr(report, "model_dump"):
        return report.model_dump(mode="json")
    return report if isinstance(report, dict) else None


async def run_workflow_recorded(
    workflow: Any, incident_request: str, call_log: CallLog
) -> dict[str, Any]:
    """Run the workflow once and return the run-output contract; never resumes an interrupt."""
    recorder = TrajectoryRecorder()
    config = {
        "configurable": {"thread_id": f"evaluation:{uuid4()}"},
        "callbacks": [recorder],
    }
    graph_path: list[str] = []
    interrupts: list[dict[str, Any]] = []
    async for chunk in workflow.astream(
        {"incident_request": incident_request, "incident_business_status": "OPEN"},
        config=config,
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            if node == "__interrupt__":
                interrupts.extend(_classify_interrupt(item.value) for item in update)
            else:
                graph_path.append(node)
    values = (await workflow.aget_state(config)).values
    return {
        "report": _report_json(values.get("report")),
        "delegations": list(call_log) if call_log else recorder.delegation_calls,
        **recorder.as_outputs(),
        "graph_path": graph_path,
        "interrupts": interrupts,
        "lifecycle": values.get("investigation_lifecycle"),
        "errors": values.get("errors") or [],
    }

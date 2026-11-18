"""Throwaway spike: compare three ways to capture an investigation trajectory.

(a) a callback handler recording on_tool_start, (b) astream(stream_mode="updates") for node
names, (c) reading tool runs back from LangSmith. Deleted once the real capture lands.
"""

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

for flag in (
    "JIRA_MCP_ENABLED",
    "MONGODB_MCP_ENABLED",
    "GITHUB_MCP_ENABLED",
    "CLOUDWATCH_MCP_ENABLED",
):
    os.environ[flag] = "false"
os.environ["LANGSMITH_TRACING"] = "true"

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import Client

from evaluation.scenarios.investigation_reports import (
    INVESTIGATION_REPORT_SCENARIOS,
)
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)
from incidentflow.agent.orchestration.supervisor import (
    build_investigation_supervisor,
)


class ToolRecorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def on_tool_start(
        self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs
    ):
        self.calls.append(
            {
                "name": kwargs.get("name") or (serialized or {}).get("name"),
                "inputs": inputs if inputs is not None else input_str,
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
            }
        )


async def main() -> None:
    scenario = next(s for s in INVESTIGATION_REPORT_SCENARIOS if s.name == "EVAL-PAY-001")
    workflow = build_investigation_workflow(
        build_investigation_supervisor(), checkpointer=InMemorySaver()
    )
    recorder = ToolRecorder()
    root_id = uuid4()
    config = {
        "configurable": {"thread_id": f"spike:{uuid4()}"},
        "callbacks": [recorder],
        "run_id": root_id,
    }
    nodes: list[str] = []
    interrupts: list[Any] = []
    async for chunk in workflow.astream(
        {"incident_request": scenario.incident_request, "incident_business_status": "OPEN"},
        config=config,
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            nodes.append(node)
            if node == "__interrupt__":
                interrupts.append(update)
    state = await workflow.aget_state(config)

    print("=== (b) node path:", nodes)
    print("=== (b) __interrupt__ chunks:", interrupts)
    print("=== final state keys:", sorted(state.values), "next:", state.next)
    print("=== report present:", state.values.get("report") is not None)
    print("=== (a) callback tool calls:", len(recorder.calls))
    for call in recorder.calls:
        print("  ", {**call, "inputs": str(call["inputs"])[:100]})

    wait_for_all_tracers()
    client = Client()
    await asyncio.sleep(5)
    runs = list(client.list_runs(trace_id=UUID(str(root_id)), run_type="tool"))
    print("=== (c) LangSmith tool runs:", len(runs))
    for run in runs:
        print("  ", {"name": run.name, "id": str(run.id), "parent": str(run.parent_run_id)})


if __name__ == "__main__":
    asyncio.run(main())

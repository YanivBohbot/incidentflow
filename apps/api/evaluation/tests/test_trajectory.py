from typing import Any, TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import ensure_config
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from evaluation.harness.fixtures import CallLog
from evaluation.harness.trajectory import TrajectoryRecorder, run_workflow_recorded


class State(TypedDict, total=False):
    incident_request: str
    report: Any
    investigation_lifecycle: str
    errors: list[str]


@tool
async def searchJiraIssuesUsingJql(jql: str) -> str:
    """Search Jira."""
    return "ok"


@tool
async def ask_it_operations(incident_context: str) -> str:
    """Delegate."""
    return "ok"


@tool
async def ask_knowledge(incident_context: str) -> str:
    """Outer delegation that invokes an inner tool with the propagated child config."""
    return await searchJiraIssuesUsingJql.ainvoke({"jql": "x"}, ensure_config())


@pytest.fixture(autouse=True)
def _no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _two_node_graph(node_a: Any) -> Any:
    async def b(state: State) -> dict[str, Any]:
        return {"investigation_lifecycle": "COMPLETED", "report": {"summary": "done"}}

    graph = StateGraph(State)
    graph.add_node("a", node_a)
    graph.add_node("b", b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    return graph.compile(checkpointer=InMemorySaver())


@pytest.mark.anyio
async def test_recorder_captures_nested_tool_calls_and_skips_delegations() -> None:
    recorder = TrajectoryRecorder()

    async def a(state: State, config: RunnableConfig) -> dict[str, Any]:
        await ask_it_operations.ainvoke({"incident_context": "c"}, config)
        await searchJiraIssuesUsingJql.ainvoke({"jql": "project = X"}, config)
        return {}

    workflow = _two_node_graph(a)
    await workflow.ainvoke(
        {"incident_request": "r"},
        config={"configurable": {"thread_id": "t"}, "callbacks": [recorder]},
    )
    assert recorder.nested_tool_calls == [
        {"agent": None, "tool": "searchJiraIssuesUsingJql", "args": {"jql": "project = X"}}
    ]
    assert recorder.as_outputs()["nested_tool_calls"] == recorder.nested_tool_calls


@pytest.mark.anyio
async def test_recorder_attributes_nested_call_to_enclosing_delegation() -> None:
    recorder = TrajectoryRecorder()

    async def a(state: State, config: RunnableConfig) -> dict[str, Any]:
        await ask_knowledge.ainvoke({"incident_context": "c"}, config)
        return {}

    await _two_node_graph(a).ainvoke(
        {"incident_request": "r"},
        config={"configurable": {"thread_id": "t"}, "callbacks": [recorder]},
    )
    assert [c["agent"] for c in recorder.as_outputs()["nested_tool_calls"]] == ["ask_knowledge"]
    assert [c["tool"] for c in recorder.nested_tool_calls] == ["searchJiraIssuesUsingJql"]


@pytest.mark.anyio
async def test_run_workflow_recorded_returns_graph_path_in_order() -> None:
    async def a(state: State) -> dict[str, Any]:
        return {}

    call_log: CallLog = [{"tool": "ask_knowledge", "args": {}}]
    out = await run_workflow_recorded(_two_node_graph(a), "request", call_log)
    assert out["graph_path"] == ["a", "b"]
    assert out["delegations"] == call_log
    assert out["lifecycle"] == "COMPLETED"
    assert out["report"] == {"summary": "done"}
    assert out["interrupts"] == []


@pytest.mark.anyio
async def test_run_workflow_recorded_records_report_review_interrupt_without_resuming() -> None:
    async def a(state: State) -> dict[str, Any]:
        return {"report": {"summary": "drafted"}, "investigation_lifecycle": "RUNNING"}

    async def review(state: State) -> dict[str, Any]:
        interrupt({"question": "approve?"})
        return {"investigation_lifecycle": "COMPLETED"}

    graph = StateGraph(State)
    graph.add_node("a", a)
    graph.add_node("review", review)
    graph.add_edge(START, "a")
    graph.add_edge("a", "review")
    graph.add_edge("review", END)
    out = await run_workflow_recorded(graph.compile(checkpointer=InMemorySaver()), "r", [])
    assert out["interrupts"] == [{"kind": "report_review", "tool": None}]
    assert out["report"] == {"summary": "drafted"}
    assert out["lifecycle"] == "RUNNING"


@pytest.mark.anyio
async def test_run_workflow_recorded_classifies_jira_write_interrupt() -> None:
    async def a(state: State) -> dict[str, Any]:
        interrupt({"action_requests": [{"name": "createJiraIssue", "args": {}}]})
        return {}

    out = await run_workflow_recorded(_two_node_graph(a), "request", [])
    assert out["interrupts"] == [{"kind": "jira_write", "tool": "createJiraIssue"}]

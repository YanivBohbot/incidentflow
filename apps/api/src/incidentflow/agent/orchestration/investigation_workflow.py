"""A small, durable LangGraph workflow for one incident investigation."""

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, Literal

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt
from pydantic import ValidationError

from incidentflow.agent.orchestration.failure_policy import classify_node_failure
from incidentflow.agent.orchestration.review_policy import accepted_human_review
from incidentflow.agent.orchestration.states.investigation import (
    InvestigationWorkflowInput,
    InvestigationWorkflowOutput,
    InvestigationWorkflowState,
)
from incidentflow.domain.human_review.models import HumanReviewDecision


def _await_in_worker(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Await an async supervisor without nesting FastAPI's running event loop."""
    result: dict[str, Any] = {}

    def run() -> None:
        try:
            result["value"] = asyncio.run(coroutine)
        except Exception as error:  # noqa: BLE001 - handled by LangGraph's node handler.
            result["error"] = error

    worker = Thread(target=run, daemon=True)
    worker.start()
    worker.join()
    if error := result.get("error"):
        raise error
    return result["value"]


def validate_request(state: InvestigationWorkflowState) -> dict:
    """Reject an empty or oversized request before any external work starts."""
    request = state["incident_request"].strip()
    if not request:
        return {"is_valid_request": False, "errors": ["incident_request must not be empty."]}
    if len(request) > 5000:
        return {"is_valid_request": False, "errors": ["incident_request must not exceed 5000 characters."]}
    return {"incident_request": request, "is_valid_request": True, "errors": []}


def route_after_validation(state: InvestigationWorkflowState) -> Literal["investigate", "fail"]:
    """Continue only after input validation succeeds."""
    return "investigate" if state["is_valid_request"] else "fail"


def handle_node_failure(_state: InvestigationWorkflowState, error: NodeError) -> Command:
    """Turn exhausted node retries into a safe failure without raw provider details."""
    failure = classify_node_failure(error.node, error.error)
    return Command(update={"errors": [failure.message]}, goto="fail")


def build_investigation_workflow(supervisor: Any | None = None, *, checkpointer: Any | None = None):
    """Build validate → investigate → optional review → finalize/fail."""

    def investigate(state: InvestigationWorkflowState) -> dict:
        """Ask the supervisor for the structured incident report."""
        active_supervisor = supervisor
        if active_supervisor is None:
            from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor

            active_supervisor = build_investigation_supervisor()
        payload = {"messages": [{"role": "user", "content": state["incident_request"]}]}
        if hasattr(active_supervisor, "ainvoke"):
            result = _await_in_worker(active_supervisor.ainvoke(payload, config={"recursion_limit": 14}))
        else:
            result = active_supervisor.invoke(payload, config={"recursion_limit": 14})
        report = result["structured_response"]
        return {"report": report, "human_review": accepted_human_review(report)}

    def route_after_investigation(state: InvestigationWorkflowState) -> Literal["review", "finalize"]:
        """Pause only when policy accepted a review payload."""
        return "review" if state["human_review"] is not None else "finalize"

    def review(state: InvestigationWorkflowState) -> Command:
        """Pause for a JSON-safe decision; no Jira write happens inside this graph."""
        payload = interrupt(state["human_review"].model_dump(mode="json"))
        try:
            decision = HumanReviewDecision.model_validate(payload)
        except ValidationError:
            return Command(update={"errors": ["The submitted human review decision was invalid."]}, goto="fail")
        return Command(update={"human_review_decision": decision}, goto="finalize")

    def finalize(state: InvestigationWorkflowState) -> dict:
        """Return the report and optional decision for the application service to persist."""
        return {"investigation_lifecycle": "completed", "workflow_stage": "finished", "errors": state["errors"]}

    def fail(state: InvestigationWorkflowState) -> dict:
        """Return a consistent terminal failure state."""
        return {"investigation_lifecycle": "failed", "workflow_stage": "finished", "report": None, "human_review": None}

    workflow = StateGraph(InvestigationWorkflowState, input_schema=InvestigationWorkflowInput, output_schema=InvestigationWorkflowOutput)
    workflow.add_node("validate", validate_request)
    workflow.add_node("investigate", investigate, retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.0, jitter=False, retry_on=(ConnectionError, TimeoutError, OSError)), error_handler=handle_node_failure)
    workflow.add_node("review", review)
    workflow.add_node("finalize", finalize)
    workflow.add_node("fail", fail)
    workflow.add_edge(START, "validate")
    workflow.add_conditional_edges("validate", route_after_validation, ["investigate", "fail"])
    workflow.add_conditional_edges("investigate", route_after_investigation, ["review", "finalize"])
    workflow.add_edge("review", "finalize")
    workflow.add_edge("finalize", END)
    workflow.add_edge("fail", END)
    return workflow.compile(checkpointer=checkpointer)

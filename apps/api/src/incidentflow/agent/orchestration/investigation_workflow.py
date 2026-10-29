"""The durable incident investigation graph and its conditional human-review path."""

import asyncio
from collections.abc import Callable, Coroutine
from threading import Thread
from typing import Any, Literal

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt
from pydantic import ValidationError

from incidentflow.agent.orchestration.failure_policy import classify_node_failure
from incidentflow.agent.orchestration.review_policy import build_human_review_request
from incidentflow.agent.orchestration.states.investigation import (
    InvestigationWorkflowInput,
    InvestigationWorkflowOutput,
    InvestigationWorkflowState,
)
from incidentflow.domain.human_review.models import (
    HumanReviewDecision,
    HumanReviewDecisionKind,
    HumanReviewRequest,
)

ApprovedActionExecutor = Callable[
    [HumanReviewRequest, HumanReviewDecision], dict[str, object]
]


def _run_coroutine_in_worker(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Run an async supervisor from this workflow's synchronous graph node."""
    outcome: dict[str, Any] = {}

    def execute() -> None:
        """Own a temporary event loop so this thread can await the supervisor safely."""
        try:
            outcome["result"] = asyncio.run(coroutine)
        except Exception as error:  # noqa: BLE001 - propagate the original supervisor failure.
            outcome["error"] = error

    # A separate thread avoids nesting an event loop when FastAPI already owns one.
    worker = Thread(target=execute, daemon=True)
    worker.start()
    worker.join()
    if error := outcome.get("error"):
        raise error
    return outcome["result"]


def validate_incident_request(state: InvestigationWorkflowState) -> dict:
    """Validate the operator request before any specialist or external tool can run."""
    incident_request = state["incident_request"].strip()
    if not incident_request:
        return {
            "is_valid_request": False,
            "investigation_lifecycle": "failed",
            "workflow_stage": "validation_failed",
            "errors": ["incident_request must not be empty."],
            "pending_human_review": None,
            "human_review_decision": None,
            "action_result": None,
        }
    if len(incident_request) > 5000:
        return {
            "is_valid_request": False,
            "investigation_lifecycle": "failed",
            "workflow_stage": "validation_failed",
            "errors": ["incident_request must not exceed 5000 characters."],
            "pending_human_review": None,
            "human_review_decision": None,
            "action_result": None,
        }

    return {
        "incident_request": incident_request,
        "is_valid_request": True,
        "investigation_lifecycle": "running",
        "workflow_stage": "supervisor_investigation",
        "errors": [],
        "pending_human_review": None,
        "human_review_decision": None,
        "action_result": None,
    }


def route_after_validation(
    state: InvestigationWorkflowState,
) -> Literal["supervisor_investigation", "finish_failed_investigation"]:
    """Choose the safe failure end node or the supervisor node from validation state."""
    if state["is_valid_request"]:
        return "supervisor_investigation"
    return "finish_failed_investigation"


def finish_failed_investigation(state: InvestigationWorkflowState) -> dict:
    """Produce the final state for a workflow that cannot continue safely."""
    return {
        "investigation_lifecycle": "failed",
        "workflow_stage": "finished",
        "report": None,
        "pending_human_review": None,
        "action_result": None,
    }


def build_investigation_workflow(
    supervisor: Any | None = None,
    *,
    checkpointer: Any | None = None,
    action_executor: ApprovedActionExecutor | None = None,
):
    """Build the primary graph that investigates, optionally pauses, then safely concludes."""

    def run_supervisor_investigation(state: InvestigationWorkflowState) -> dict:
        """Ask the supervisor for a structured report after request validation succeeds."""
        active_supervisor = supervisor
        if active_supervisor is None:
            # Delay optional MCP imports until an investigation actually needs them.
            from incidentflow.agent.orchestration.supervisor import (
                build_investigation_supervisor,
            )

            active_supervisor = build_investigation_supervisor()

        # The supervisor receives only the normalized request held in graph state.
        payload = {"messages": [{"role": "user", "content": state["incident_request"]}]}
        config = {"recursion_limit": 14}
        if hasattr(active_supervisor, "ainvoke"):
            result = _run_coroutine_in_worker(active_supervisor.ainvoke(payload, config=config))
        else:
            result = active_supervisor.invoke(payload, config=config)

        report = result["structured_response"]
        return {
            "investigation_lifecycle": "running",
            "workflow_stage": "review_policy",
            "report": report,
            "pending_human_review": build_human_review_request(report),
        }

    def recover_from_node_failure(
        _state: InvestigationWorkflowState, error: NodeError
    ) -> Command[Literal["finish_failed_investigation"]]:
        """Convert exhausted node retries into one safe, user-facing failure route."""
        failure = classify_node_failure(error.node, error.error)
        return Command(
            update={
                "investigation_lifecycle": "failed",
                "workflow_stage": "node_failure",
                "report": None,
                "errors": [failure.message],
                "pending_human_review": None,
                "human_review_decision": None,
                "action_result": None,
            },
            goto="finish_failed_investigation",
        )

    def route_after_supervisor(
        state: InvestigationWorkflowState,
    ) -> Literal["human_review", "finalize_report", "finish_failed_investigation"]:
        """Pause only for policy-approved review; otherwise finish the report normally."""
        if state["report"] is None:
            return "finish_failed_investigation"
        if state["pending_human_review"] is not None:
            return "human_review"
        return "finalize_report"

    def human_review(
        state: InvestigationWorkflowState,
    ) -> Command[
        Literal[
            "execute_approved_action",
            "record_review_rejection",
            "request_more_information",
            "finish_failed_investigation",
        ]
    ]:
        """Pause for one JSON-safe operator decision and route only after resumption."""
        review = state["pending_human_review"]
        if review is None:
            return Command(
                update={
                    "investigation_lifecycle": "failed",
                    "workflow_stage": "review_missing",
                    "errors": ["Human review data was unavailable."],
                },
                goto="finish_failed_investigation",
            )

        # No side effects occur before interrupt: this node restarts on resume.
        decision_payload = interrupt(review.model_dump(mode="json"))
        try:
            decision = HumanReviewDecision.model_validate(decision_payload)
        except ValidationError:
            return Command(
                update={
                    "investigation_lifecycle": "failed",
                    "workflow_stage": "review_decision_invalid",
                    "errors": ["The submitted human review decision was invalid."],
                },
                goto="finish_failed_investigation",
            )

        update = {"human_review_decision": decision, "errors": []}
        if decision.decision is HumanReviewDecisionKind.APPROVE:
            return Command(update=update, goto="execute_approved_action")
        if decision.decision is HumanReviewDecisionKind.REJECT:
            return Command(update=update, goto="record_review_rejection")
        return Command(update=update, goto="request_more_information")

    def execute_approved_action(state: InvestigationWorkflowState) -> dict:
        """Execute an approved action once; this node deliberately has no retry policy."""
        review = state["pending_human_review"]
        decision = state["human_review_decision"]
        if review is None or decision is None or action_executor is None:
            raise RuntimeError("Approved action execution was not configured.")

        action_result = action_executor(review, decision)
        return {
            "investigation_lifecycle": "running",
            "workflow_stage": "report_finalization",
            "pending_human_review": None,
            "action_result": action_result,
        }

    def record_review_rejection(_state: InvestigationWorkflowState) -> dict:
        """End a rejected proposal without calling any external write integration."""
        return {
            "investigation_lifecycle": "running",
            "workflow_stage": "report_finalization",
            "pending_human_review": None,
            "action_result": {"status": "rejected"},
        }

    def request_more_information(state: InvestigationWorkflowState) -> dict:
        """Keep the review pending when an operator asks for additional evidence."""
        return {
            "investigation_lifecycle": "awaiting_human_review",
            "workflow_stage": "information_requested",
            "pending_human_review": state["pending_human_review"],
            "action_result": {"status": "information_requested"},
        }

    def finalize_report(state: InvestigationWorkflowState) -> dict:
        """Mark a completed investigation without modifying the structured report."""
        return {
            "investigation_lifecycle": "completed",
            "workflow_stage": "finished",
            "errors": state["errors"],
        }

    # StateGraph declares shared data; the edges below declare every possible path.
    workflow = StateGraph(
        InvestigationWorkflowState,
        input_schema=InvestigationWorkflowInput,
        output_schema=InvestigationWorkflowOutput,
    )
    workflow.add_node("validate_incident_request", validate_incident_request)
    workflow.add_node(
        "supervisor_investigation",
        run_supervisor_investigation,
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_interval=0.0,
            jitter=False,
            retry_on=(ConnectionError, TimeoutError, OSError),
        ),
        error_handler=recover_from_node_failure,
    )
    workflow.add_node("human_review", human_review)
    workflow.add_node(
        "execute_approved_action",
        execute_approved_action,
        error_handler=recover_from_node_failure,
    )
    workflow.add_node("record_review_rejection", record_review_rejection)
    workflow.add_node("request_more_information", request_more_information)
    workflow.add_node("finalize_report", finalize_report)
    workflow.add_node("finish_failed_investigation", finish_failed_investigation)

    workflow.add_edge(START, "validate_incident_request")
    workflow.add_conditional_edges(
        "validate_incident_request",
        route_after_validation,
        ["supervisor_investigation", "finish_failed_investigation"],
    )
    workflow.add_conditional_edges(
        "supervisor_investigation",
        route_after_supervisor,
        ["human_review", "finalize_report", "finish_failed_investigation"],
    )
    workflow.add_edge("execute_approved_action", "finalize_report")
    workflow.add_edge("record_review_rejection", "finalize_report")
    workflow.add_edge("request_more_information", END)
    workflow.add_edge("finalize_report", END)
    workflow.add_edge("finish_failed_investigation", END)

    # The checkpointer persists every node boundary and the interrupt for one thread_id.
    return workflow.compile(checkpointer=checkpointer)

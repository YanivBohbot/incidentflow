"""The explicit, durable graph for one IncidentFlow investigation."""

from functools import partial
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from incidentflow.agent.orchestration.fault_tolerance.retry_policies import (
    external_read_retry_policy,
)
from incidentflow.agent.orchestration.fault_tolerance.workflow_failures import handle_node_failure
from incidentflow.agent.orchestration.policies.human_review import accepted_human_review
from incidentflow.agent.orchestration.states.investigation import (
    InvestigationWorkflowInput,
    InvestigationWorkflowOutput,
    InvestigationWorkflowState,
)
from incidentflow.domain.human_review.models import HumanReviewDecision


def validate_request(state: InvestigationWorkflowState) -> dict:
    """Reject an empty or oversized request before external work can start."""
    request = state["incident_request"].strip()
    if not request:
        return {"is_valid_request": False, "errors": ["incident_request must not be empty."]}
    if len(request) > 5000:
        return {"is_valid_request": False, "errors": ["incident_request must not exceed 5000 characters."]}
    return {"incident_request": request, "is_valid_request": True, "errors": []}


def route_after_validation(state: InvestigationWorkflowState) -> Literal["prepare", "fail"]:
    """Route only validated input to the supervisor."""
    return "prepare" if state["is_valid_request"] else "fail"


def prepare_supervisor_input(state: InvestigationWorkflowState) -> dict:
    """Place the validated incident request into the Supervisor message state."""
    return {"messages": [{"role": "user", "content": state["incident_request"]}]}


async def investigate_with_supervisor(
    state: InvestigationWorkflowState,
    config: RunnableConfig,
    *,
    supervisor: Any,
) -> dict:
    """Call the compiled Supervisor explicitly with the parent workflow configuration.

    The operator's original request travels in the config so a delegation tool can read it
    word for word, even when the supervisor paraphrases it in the tool arguments.
    """
    configurable = {**config.get("configurable", {}), "incident_request": state["incident_request"]}
    result = await supervisor.ainvoke(
        {"messages": state["messages"]},
        config={**config, "configurable": configurable},
    )
    return {
        "messages": result.get("messages", []),
        "structured_response": result.get("structured_response"),
    }


def capture_supervisor_report(state: InvestigationWorkflowState) -> dict:
    """Copy the Supervisor's structured response into the investigation contract."""
    report = state.get("structured_response")
    if report is None:
        return {
            "report": None,
            "human_review": None,
            "errors": ["The Supervisor completed without a structured report."],
        }
    return {"report": report, "human_review": accepted_human_review(report)}


def route_after_investigation(
    state: InvestigationWorkflowState,
) -> Literal["review", "finalize", "fail"]:
    """Fail without a report, pause only for a policy-accepted review, otherwise finalize."""
    if state.get("report") is None:
        return "fail"
    return "review" if state.get("human_review") is not None else "finalize"


def review(state: InvestigationWorkflowState) -> Command:
    """Pause only for report-level reviews; Jira writes pause inside the Jira specialist."""
    try:
        decision = HumanReviewDecision.model_validate(interrupt(state["human_review"].model_dump(mode="json")))
    except ValidationError:
        return Command(update={"errors": ["The submitted human review decision was invalid."]}, goto="fail")
    return Command(update={"human_review_decision": decision}, goto="finalize")


def finalize(state: InvestigationWorkflowState) -> dict:
    """Return the report and optional decision to the application service."""
    return {"investigation_lifecycle": "completed", "workflow_stage": "finished", "errors": state["errors"]}


def fail(_state: InvestigationWorkflowState) -> dict:
    """Return a safe terminal state when validation or investigation fails."""
    return {"investigation_lifecycle": "failed", "workflow_stage": "finished", "report": None, "human_review": None}


def build_investigation_workflow(
    supervisor: Any, *, checkpointer: BaseCheckpointSaver[Any] | None = None
):
    """Build the workflow that calls the compiled Supervisor explicitly in its investigate node."""
    workflow = StateGraph(
        InvestigationWorkflowState,
        input_schema=InvestigationWorkflowInput,
        output_schema=InvestigationWorkflowOutput,
    )
    workflow.add_node("validate", validate_request)
    workflow.add_node("prepare", prepare_supervisor_input)
    workflow.add_node(
        "investigate",
        partial(investigate_with_supervisor, supervisor=supervisor),
        retry_policy=external_read_retry_policy(),
        error_handler=handle_node_failure,
    )
    workflow.add_node("capture_report", capture_supervisor_report)
    workflow.add_node("review", review)
    workflow.add_node("finalize", finalize)
    workflow.add_node("fail", fail)
    workflow.add_edge(START, "validate")
    workflow.add_conditional_edges("validate", route_after_validation, ["prepare", "fail"])
    workflow.add_edge("prepare", "investigate")
    workflow.add_edge("investigate", "capture_report")
    workflow.add_conditional_edges(
        "capture_report", route_after_investigation, ["review", "finalize", "fail"]
    )
    workflow.add_edge("review", "finalize")
    workflow.add_edge("finalize", END)
    workflow.add_edge("fail", END)
    return workflow.compile(checkpointer=checkpointer)

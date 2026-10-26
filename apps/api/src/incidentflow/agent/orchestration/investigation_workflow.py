from collections.abc import Callable
from typing import Any, Literal, TypedDict

from langchain_openai.chat_models.base import OpenAIAuthenticationError
from langgraph.graph import END, START, StateGraph

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor


class InvestigationWorkflowInput(TypedDict):
    incident_request: str
    incident_business_status: str


class InvestigationWorkflowOutput(TypedDict):
    investigation_lifecycle: str
    workflow_stage: str
    report: InvestigationReport | None
    errors: list[str]


class InvestigationWorkflowState(InvestigationWorkflowInput, InvestigationWorkflowOutput):
    is_valid_request: bool


def validate_incident_request(state: InvestigationWorkflowState) -> dict:
    incident_request = state["incident_request"].strip()
    if not incident_request:
        return {
            "is_valid_request": False,
            "investigation_lifecycle": "failed",
            "workflow_stage": "validation_failed",
            "errors": ["incident_request must not be empty."],
        }

    return {
        "is_valid_request": True,
        "investigation_lifecycle": "running",
        "workflow_stage": "supervisor_investigation",
        "errors": [],
    }


def route_after_validation(
    state: InvestigationWorkflowState,
) -> Literal["supervisor_investigation", "finish_failed_investigation"]:
    if state["is_valid_request"]:
        return "supervisor_investigation"
    return "finish_failed_investigation"


def finish_failed_investigation(state: InvestigationWorkflowState) -> dict:
    return {
        "investigation_lifecycle": "failed",
        "workflow_stage": "finished",
        "report": None,
    }


def build_investigation_workflow(
    supervisor_factory: Callable[[], Any] = build_investigation_supervisor,
):
    def run_supervisor_investigation(state: InvestigationWorkflowState) -> dict:
        supervisor = supervisor_factory()

        try:
            result = supervisor.invoke(
                {"messages": [{"role": "user", "content": state["incident_request"]}]},
                config={"recursion_limit": 14},
            )
        except OpenAIAuthenticationError:
            return {
                "investigation_lifecycle": "failed",
                "workflow_stage": "supervisor_failed",
                "report": None,
                "errors": ["OpenAI authentication failed."],
            }

        return {
            "investigation_lifecycle": "running",
            "workflow_stage": "report_finalization",
            "report": result["structured_response"],
        }

    def route_after_supervisor(
        state: InvestigationWorkflowState,
    ) -> Literal["finalize_report", "finish_failed_investigation"]:
        if state["report"] is not None:
            return "finalize_report"
        return "finish_failed_investigation"

    def finalize_report(state: InvestigationWorkflowState) -> dict:
        return {
            "investigation_lifecycle": "completed",
            "workflow_stage": "finished",
            "errors": state["errors"],
        }

    workflow = StateGraph(
        InvestigationWorkflowState,
        input_schema=InvestigationWorkflowInput,
        output_schema=InvestigationWorkflowOutput,
    )
    workflow.add_node("validate_incident_request", validate_incident_request)
    workflow.add_node("supervisor_investigation", run_supervisor_investigation)
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
        ["finalize_report", "finish_failed_investigation"],
    )
    workflow.add_edge("finalize_report", END)
    workflow.add_edge("finish_failed_investigation", END)
    return workflow.compile()

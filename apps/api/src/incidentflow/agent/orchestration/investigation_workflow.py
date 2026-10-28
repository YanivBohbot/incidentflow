import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, Literal, TypedDict

from langchain_openai.chat_models.base import OpenAIAuthenticationError
from langgraph.graph import END, START, StateGraph

from incidentflow.agent.agents_specialist.contracts import InvestigationReport


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


def _run_coroutine_in_worker(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Bridge async MCP work into the workflow's synchronous node execution."""
    outcome: dict[str, Any] = {}

    def execute() -> None:
        """Run the coroutine in an event loop owned by this short-lived worker."""
        try:
            outcome["result"] = asyncio.run(coroutine)
        except BaseException as error:  # noqa: BLE001 - re-raise in the workflow worker.
            outcome["error"] = error

    worker = Thread(target=execute, daemon=True)
    worker.start()
    worker.join()
    if error := outcome.get("error"):
        raise error
    return outcome["result"]


def validate_incident_request(state: InvestigationWorkflowState) -> dict:
    incident_request = state["incident_request"].strip()
    if not incident_request:
        return {
            "is_valid_request": False,
            "investigation_lifecycle": "failed",
            "workflow_stage": "validation_failed",
            "errors": ["incident_request must not be empty."],
        }
    if len(incident_request) > 5000:
        return {
            "is_valid_request": False,
            "investigation_lifecycle": "failed",
            "workflow_stage": "validation_failed",
            "errors": ["incident_request must not exceed 5000 characters."],
        }

    return {
        "incident_request": incident_request,
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
    supervisor: Any | None = None,
    *,
    checkpointer: Any | None = None,
):
    def run_supervisor_investigation(state: InvestigationWorkflowState) -> dict:
        """Run async specialist tools safely from the durable synchronous workflow node."""
        active_supervisor = supervisor
        if active_supervisor is None:
            # Import only when an investigation starts; FastAPI can still start
            # without loading optional MCP integrations.
            from incidentflow.agent.orchestration.supervisor import (
                build_investigation_supervisor,
            )

            active_supervisor = build_investigation_supervisor()
        try:
            payload = {"messages": [{"role": "user", "content": state["incident_request"]}]}
            config = {"recursion_limit": 14}
            if hasattr(active_supervisor, "ainvoke"):
                result = _run_coroutine_in_worker(active_supervisor.ainvoke(payload, config=config))
            else:
                result = active_supervisor.invoke(payload, config=config)
        except OpenAIAuthenticationError:
            return {
                "investigation_lifecycle": "failed",
                "workflow_stage": "supervisor_failed",
                "report": None,
                "errors": ["OpenAI authentication failed."],
            }
        except Exception as error:  # noqa: BLE001 - persist a safe operator diagnosis.
            return {
                "investigation_lifecycle": "failed",
                "workflow_stage": "supervisor_failed",
                "report": None,
                "errors": [f"Supervisor execution failed: {type(error).__name__}."],
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
    return workflow.compile(checkpointer=checkpointer)

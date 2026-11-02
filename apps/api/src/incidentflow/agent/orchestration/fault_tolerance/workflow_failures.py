"""Safe failure handling shared by LangGraph workflows."""

from langgraph.errors import GraphInterrupt, NodeError
from langgraph.types import Command

from incidentflow.agent.orchestration.fault_tolerance.failure_policy import (
    classify_node_failure,
)


def handle_node_failure(_state: object, error: NodeError) -> Command:
    """Route genuine node failures to fail, while preserving LangGraph HITL control flow."""
    if isinstance(error.error, GraphInterrupt):
        raise error.error
    failure = classify_node_failure(error.node, error.error)
    return Command(update={"errors": [failure.message]}, goto="fail")

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class JiraActionReviewState(TypedDict, total=False):
    proposal_id: str
    investigation_id: str
    action: str
    payload: dict[str, str]
    evidence_references: list[str]
    decision: str


def build_jira_action_workflow(*, checkpointer: Any):
    """Build the durable human-review pause that precedes any Jira mutation."""

    def request_human_decision(state: JiraActionReviewState) -> dict[str, str]:
        decision = interrupt(
            {
                "proposal_id": state["proposal_id"],
                "investigation_id": state["investigation_id"],
                "action": state["action"],
                "payload": state["payload"],
                "evidence_references": state["evidence_references"],
            }
        )
        return {"decision": str(decision)}

    workflow = StateGraph(JiraActionReviewState)
    workflow.add_node("request_human_decision", request_human_decision)
    workflow.add_edge(START, "request_human_decision")
    workflow.add_edge("request_human_decision", END)
    return workflow.compile(checkpointer=checkpointer)

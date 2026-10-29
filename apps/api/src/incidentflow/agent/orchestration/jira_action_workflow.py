from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from incidentflow.agent.orchestration.states.jira_action import JiraActionReviewState


def build_jira_action_workflow(*, checkpointer: Any):
    """Build the durable human-review pause that precedes any Jira mutation."""

    def request_human_decision(state: JiraActionReviewState) -> dict[str, str]:
        """Pause the graph and store its proposal until the operator resumes this thread."""
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

    # This graph is compiled once at API startup and reused for every proposal thread.
    workflow = StateGraph(JiraActionReviewState)
    workflow.add_node("request_human_decision", request_human_decision)
    workflow.add_edge(START, "request_human_decision")
    workflow.add_edge("request_human_decision", END)
    return workflow.compile(checkpointer=checkpointer)

"""Rules for report reviews and tool-level Jira approval payloads."""

from typing import Any

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewType,
)


def accepted_human_review(report: InvestigationReport) -> HumanReview | None:
    """Return the review only when deterministic policy permits a workflow pause."""
    review = report.human_review
    if review is None:
        return None
    if review.review_type is HumanReviewType.JIRA_WRITE:
        return None
    return review


def jira_write_review_from_interrupt(payload: object) -> HumanReview | None:
    """Translate one LangChain Jira tool interrupt into the UI review contract."""
    if not isinstance(payload, dict):
        return None
    action_requests = payload.get("action_requests")
    if not isinstance(action_requests, list) or not action_requests:
        return None
    action = action_requests[0]
    if not isinstance(action, dict):
        return None
    name = action.get("name")
    arguments = action.get("arguments", action.get("args"))
    description = action.get("description")
    if name not in {"createJiraIssue", "addOrEditJiraIssueComment"}:
        return None
    return HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason=str(description or f"Approve Jira tool call: {name}"),
        draft={"tool_name": name, "arguments": arguments if isinstance(arguments, dict) else {}},
    )


def jira_tool_resume_payload(decision: HumanReviewDecision) -> dict[str, list[dict[str, Any]]]:
    """Map the product review decision onto LangChain's tool-review protocol."""
    if decision.decision.value == "APPROVE":
        return {"decisions": [{"type": "approve"}]}
    return {
        "decisions": [
            {
                "type": "reject",
                "message": decision.reason or "The operator rejected this Jira write.",
            }
        ]
    }

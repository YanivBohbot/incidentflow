"""Rules for report reviews and tool-level Jira approval payloads."""

from typing import Any

from incidentflow.agent.findings import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewType,
)

# Only the text of a Jira write may be edited by the operator. The target (site, project,
# issue type, issue key) stays exactly what the agent proposed and the operator reviewed.
JIRA_EDITABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "createJiraIssue": ("summary", "description"),
    "addOrEditJiraIssueComment": ("commentBody",),
}


class HumanReviewEditError(ValueError):
    """The operator tried to edit a Jira argument that is not editable."""


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
    if name not in JIRA_EDITABLE_FIELDS:
        return None
    return HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason=str(description or f"Approve Jira tool call: {name}"),
        draft={
            "tool_name": name,
            "arguments": arguments if isinstance(arguments, dict) else {},
            "editable_fields": list(JIRA_EDITABLE_FIELDS[name]),
        },
    )


def jira_tool_resume_payload(
    decision: HumanReviewDecision, review: HumanReview | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Map the product review decision onto LangChain's tool-review protocol.

    APPROVE without edits -> "approve"; APPROVE with edited text -> "edit" (the original
    arguments with only the permitted fields replaced); REJECT and REQUEST_INFORMATION ->
    "reject" with the operator's reason, which the Jira agent reads as the tool result.
    """
    if decision.decision.value != "APPROVE":
        return {
            "decisions": [
                {
                    "type": "reject",
                    "message": decision.reason or "The operator rejected this Jira write.",
                }
            ]
        }
    if not decision.edited_draft:
        return {"decisions": [{"type": "approve"}]}
    if review is None:
        raise HumanReviewEditError("Edits require the paused Jira review.")
    tool_name = review.draft.get("tool_name")
    editable = JIRA_EDITABLE_FIELDS.get(str(tool_name), ())
    forbidden = sorted(set(decision.edited_draft) - set(editable))
    if forbidden:
        raise HumanReviewEditError(f"These Jira fields cannot be edited: {', '.join(forbidden)}.")
    original = review.draft.get("arguments")
    arguments = dict(original) if isinstance(original, dict) else {}
    arguments.update(decision.edited_draft)
    return {
        "decisions": [
            {"type": "edit", "edited_action": {"name": str(tool_name), "args": arguments}}
        ]
    }

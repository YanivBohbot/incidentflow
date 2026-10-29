"""State contract for the durable Jira human-review workflow."""

from typing import TypedDict


class JiraActionReviewState(TypedDict, total=False):
    """The review data checkpointed while a Jira proposal awaits a human decision."""

    proposal_id: str
    investigation_id: str
    action: str
    payload: dict[str, str]
    evidence_references: list[str]
    decision: str

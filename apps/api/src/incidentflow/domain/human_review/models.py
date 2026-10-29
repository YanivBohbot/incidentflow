"""JSON-safe contracts for conditional human review in an investigation."""

from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class HumanReviewType(str, Enum):
    """The policy-controlled situations that may pause a workflow."""

    JIRA_WRITE = "JIRA_WRITE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class HumanReviewDecisionKind(str, Enum):
    """The choices an operator may make after a workflow interruption."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"


class HumanReview(BaseModel):
    """The single review payload paused in the workflow and shown to an operator."""

    id: UUID = Field(default_factory=uuid4)
    review_type: HumanReviewType
    reason: str = Field(min_length=1, max_length=2_000)
    evidence_references: list[str] = Field(default_factory=list, max_length=50)
    draft: dict[str, str] = Field(default_factory=dict)
class HumanReviewDecision(BaseModel):
    """The explicit JSON-safe response supplied by an authenticated operator."""

    decision: HumanReviewDecisionKind
    actor: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=2_000)
    edited_draft: dict[str, str] = Field(default_factory=dict)

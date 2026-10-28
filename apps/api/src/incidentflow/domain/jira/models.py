from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class JiraIssueCreateRequest(BaseModel):
    """Payload proposed for the official Jira MCP create operation."""

    model_config = ConfigDict(populate_by_name=True)

    cloud_id: str = Field(alias="cloudId", min_length=1)
    project_key: str = Field(alias="projectKey", min_length=1, max_length=50)
    issue_type: str = Field(alias="issueType", min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    def tool_arguments(self) -> dict[str, str]:
        return self.model_dump(by_alias=True)


class JiraIssueCommentRequest(BaseModel):
    """Payload proposed for adding an investigation note to a Jira issue."""

    model_config = ConfigDict(populate_by_name=True)

    cloud_id: str = Field(alias="cloudId", min_length=1)
    issue_id_or_key: str = Field(alias="issueIdOrKey", min_length=1, max_length=100)
    comment_body: str = Field(alias="commentBody", min_length=1, max_length=10000)
    def tool_arguments(self) -> dict[str, str]:
        return self.model_dump(by_alias=True)


class JiraProposalAction(str, Enum):
    CREATE_ISSUE = "CREATE_ISSUE"
    ADD_COMMENT = "ADD_COMMENT"


class JiraProposalState(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


def utc_now() -> datetime:
    return datetime.now(UTC)


class JiraActionProposal(BaseModel):
    """A persisted action waiting for a human decision before Jira is changed."""

    id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    action: JiraProposalAction
    state: JiraProposalState = JiraProposalState.PENDING
    payload: dict[str, str]
    result_payload: dict[str, Any] | None = None
    error_message: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejected_at: datetime | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None
    cancellation_reason: str | None = None
    proposed_by: str = "local-operator"
    decision_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JiraMCPResult(BaseModel):
    operation: str
    result: Any


class JiraProposalDecision(BaseModel):
    """A local human decision recorded before any Jira mutation can occur."""

    actor: str = Field(default="local-operator", min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)

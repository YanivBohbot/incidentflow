from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JiraIssueCreateRequest(BaseModel):
    """Human-approved payload for the official Jira MCP create operation."""

    model_config = ConfigDict(populate_by_name=True)

    cloud_id: str = Field(alias="cloudId", min_length=1)
    project_key: str = Field(alias="projectKey", min_length=1, max_length=50)
    issue_type: str = Field(alias="issueType", min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    approved: Literal[True] = Field(
        description="Explicit human approval required immediately before creating the issue."
    )

    def tool_arguments(self) -> dict[str, str]:
        return self.model_dump(by_alias=True, exclude={"approved"})


class JiraIssueCommentRequest(BaseModel):
    """Human-approved payload for adding an investigation note to a Jira issue."""

    model_config = ConfigDict(populate_by_name=True)

    cloud_id: str = Field(alias="cloudId", min_length=1)
    issue_id_or_key: str = Field(alias="issueIdOrKey", min_length=1, max_length=100)
    comment_body: str = Field(alias="commentBody", min_length=1, max_length=10000)
    approved: Literal[True] = Field(
        description="Explicit human approval required immediately before adding the comment."
    )

    def tool_arguments(self) -> dict[str, str]:
        return self.model_dump(by_alias=True, exclude={"approved"})


class JiraMCPResult(BaseModel):
    operation: str
    result: Any

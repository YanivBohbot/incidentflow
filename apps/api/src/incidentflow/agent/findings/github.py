"""Finding returned by the GitHub agent."""

from pydantic import BaseModel, Field

from incidentflow.agent.findings.evidence import InvestigationEvidence


class GitHubFinding(BaseModel):
    summary: str = Field(
        description="Concise summary of recent code changes relevant to the incident."
    )
    repository: str = Field(description="Repository actually examined through GitHub MCP.")
    related_pull_requests: list[str] = Field(
        default_factory=list,
        description="Pull request identifiers or URLs returned by GitHub MCP.",
    )
    related_commits: list[str] = Field(
        default_factory=list,
        description="Commit SHAs or stable commit identifiers returned by GitHub MCP.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed GitHub observations supporting the summary.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Unverified possible links between code changes and the incident.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="GitHub access, time-window, or correlation gaps.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the code-change assessment, from 0.0 to 1.0.",
    )

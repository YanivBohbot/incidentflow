from typing import Literal

from pydantic import BaseModel, Field, model_validator


class InvestigationEvidence(BaseModel):
    source: str = Field(description="System or document that produced this evidence.")
    detail: str = Field(description="Exact, concise evidence returned by the source.")
    source_status: Literal["simulated", "live", "unavailable"] = Field(
        description="Whether the source is simulated, live, or unavailable during the investigation."
    )


class ITOperationsFinding(BaseModel):
    summary: str = Field(
        description="Concise operational summary based only on available evidence."
    )
    related_ticket_ids: list[str] = Field(
        default_factory=list,
        description="Related Jira or incident ticket identifiers found by the available tools.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed evidence supporting the summary.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Unverified possible causes, kept separate from evidence.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the summary, from 0.0 to 1.0.",
    )


class DataIntelligenceFinding(BaseModel):
    summary: str = Field(
        description="Concise technical summary based only on available events and logs."
    )
    timeline: list[str] = Field(
        default_factory=list,
        description="Ordered operational events relevant to the investigation.",
    )
    error_signatures: list[str] = Field(
        default_factory=list,
        description="Observed error messages, codes, or patterns.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed technical evidence.",
    )
    suspected_root_causes: list[str] = Field(
        default_factory=list,
        description="Unverified technical explanations, separate from evidence.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the technical assessment, from 0.0 to 1.0.",
    )


class KnowledgeFinding(BaseModel):
    summary: str = Field(
        description="Concise recommendation grounded in the retrieved documentation."
    )
    relevant_documents: list[str] = Field(
        default_factory=list,
        description="Titles or stable identifiers of the retrieved documents.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed excerpts or facts retrieved from documentation.",
    )
    recommended_steps: list[str] = Field(
        default_factory=list,
        description="Read-only or approval-required next steps derived from the evidence.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Gaps, missing documents, or constraints in the available knowledge.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the documentation-grounded recommendation, from 0.0 to 1.0.",
    )


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


class InvestigationReport(BaseModel):
    summary: str = Field(
        description="Consolidated incident assessment based on specialist findings."
    )
    agents_consulted: list[str] = Field(
        default_factory=list,
        description="Technical names of the specialists consulted for this report.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed evidence collected from specialist findings.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Unverified explanations, kept separate from observed evidence.",
    )
    proposed_actions: list[str] = Field(
        default_factory=list,
        description="Recommendations only; no action is executed by this report.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known gaps, conflicts, or source limitations.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the consolidated report, from 0.0 to 1.0.",
    )

    @model_validator(mode="after")
    def normalize_unavailable_source_statuses(self) -> "InvestigationReport":
        """Keep integration outages distinct from simulated or live evidence."""
        for evidence in self.evidence:
            detail = evidence.detail.casefold()
            if (
                "mcp was unavailable during this investigation" in detail
                or "retrieval was unavailable during this investigation" in detail
            ):
                evidence.source_status = "unavailable"
        return self

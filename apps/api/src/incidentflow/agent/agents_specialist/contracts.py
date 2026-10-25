from typing import Literal

from pydantic import BaseModel, Field


class InvestigationEvidence(BaseModel):
    source: str = Field(description="System or document that produced this evidence.")
    detail: str = Field(description="Exact, concise evidence returned by the source.")
    source_status: Literal["simulated", "live"] = Field(
        description="Whether the source is simulated or connected to a live system."
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
        description="Known gaps, conflicts, or simulated-source limitations.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the consolidated report, from 0.0 to 1.0.",
    )

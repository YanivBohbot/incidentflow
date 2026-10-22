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

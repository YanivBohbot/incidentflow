"""Finding returned by the IT Operations (Jira) agent."""

from pydantic import BaseModel, Field

from incidentflow.agent.findings.evidence import InvestigationEvidence


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

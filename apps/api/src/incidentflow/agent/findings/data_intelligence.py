"""Finding returned by the Data Intelligence (MongoDB) agent."""

from typing import Literal

from pydantic import BaseModel, Field

from incidentflow.agent.findings.evidence import InvestigationEvidence


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
    data_classification: Literal["production", "synthetic", "unknown"] = Field(
        default="unknown",
        description=(
            "Whether the observed event documents represent production, synthetic test data, "
            "or an unknown dataset. This is distinct from whether the MongoDB integration was live."
        ),
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Dataset or observability limitations that constrain the technical conclusion.",
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

"""Finding returned by the Knowledge (Pinecone) agent."""

from pydantic import BaseModel, Field

from incidentflow.agent.findings.evidence import InvestigationEvidence


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

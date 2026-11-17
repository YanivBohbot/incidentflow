"""Final report written by the supervisor from the specialist findings."""

from pydantic import BaseModel, Field, model_validator

from incidentflow.agent.findings.evidence import InvestigationEvidence
from incidentflow.domain.human_review.models import HumanReview


class CausalStep(BaseModel):
    """One link of the chain that explains where the problem comes from."""

    label: str = Field(description="Short name of the step, at most six words.")
    detail: str = Field(description="One sentence with the concrete figure or fact behind it.")
    source: str = Field(
        description="Technical name of the specialist whose evidence supports this step."
    )
    verified: bool = Field(
        description="True when observed evidence supports the step; false for a hypothesis."
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
    root_cause: str | None = Field(
        default=None,
        description="One sentence naming the most likely origin of the problem.",
    )
    causal_chain: list[CausalStep] = Field(
        default_factory=list,
        description=(
            "Two to six ordered steps from the earliest cause to the customer-visible symptom."
        ),
    )
    human_review: HumanReview | None = Field(
        default=None,
        description=(
            "Optional structured request for a human review; "
            "it never authorizes an action by itself."
        ),
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
                or "mcp is unavailable because" in detail
            ):
                evidence.source_status = "unavailable"
        return self

"""State contracts for the investigation workflow."""

from typing import TypedDict

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReviewDecision,
    HumanReviewRequest,
)


class InvestigationWorkflowInput(TypedDict):
    """Fields provided when a new investigation workflow starts."""

    incident_request: str
    incident_business_status: str


class InvestigationWorkflowOutput(TypedDict):
    """Fields returned to the application when the workflow reaches an end state."""

    investigation_lifecycle: str
    workflow_stage: str
    report: InvestigationReport | None
    errors: list[str]
    pending_human_review: HumanReviewRequest | None
    human_review_decision: HumanReviewDecision | None
    action_result: dict[str, object] | None


class InvestigationWorkflowState(InvestigationWorkflowInput, InvestigationWorkflowOutput):
    """Complete checkpointed state shared by the investigation workflow nodes."""

    is_valid_request: bool

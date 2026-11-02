"""State contracts for the investigation workflow."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
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
    human_review: HumanReview | None
    human_review_decision: HumanReviewDecision | None


class InvestigationWorkflowState(InvestigationWorkflowInput, InvestigationWorkflowOutput):
    """Complete checkpointed state shared by the investigation workflow nodes."""

    is_valid_request: bool
    messages: Annotated[list[AnyMessage], add_messages]
    structured_response: InvestigationReport | None

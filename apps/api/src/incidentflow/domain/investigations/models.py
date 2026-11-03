from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from incidentflow.agent.findings import InvestigationReport
from incidentflow.domain.human_review.models import HumanReview


class InvestigationLifecycle(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utc_now() -> datetime:
    return datetime.now(UTC)


class InvestigationCreate(BaseModel):
    incident_id: UUID
    incident_request: str = Field(min_length=1, max_length=5000)
    incident_business_status: str = Field(min_length=1, max_length=50)


class InvestigationStart(BaseModel):
    incident_id: UUID
    incident_request: str = Field(min_length=1, max_length=5000)


class Investigation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    incident_request: str
    incident_business_status: str
    lifecycle: InvestigationLifecycle = InvestigationLifecycle.PENDING
    workflow_thread_id: str
    report: InvestigationReport | None = None
    human_review: HumanReview | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class InvestigationTraceStep(BaseModel):
    """One readable step of a multi-agent investigation, rebuilt from its checkpoint."""

    kind: Literal[
        "request",
        "reasoning",
        "delegation",
        "subagent_call",
        "finding",
        "limit",
        "review_pause",
        "review_decision",
        "report",
    ]
    actor: str = Field(description="Who acted: Operator, the supervisor, or a specialist.")
    title: str
    detail: str = ""
    status: Literal["live", "unavailable", "pending", "approved", "rejected", "info"] = "info"
    confidence: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

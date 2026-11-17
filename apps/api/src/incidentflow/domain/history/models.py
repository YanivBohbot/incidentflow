"""API contracts of the incident history (decision timeline and incident journal)."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IncidentEventKind(str, Enum):
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
    REVIEW_REQUESTED = "REVIEW_REQUESTED"
    REVIEW_DECIDED = "REVIEW_DECIDED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    INVESTIGATION_FAILED = "INVESTIGATION_FAILED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"
    INCIDENT_CLOSED = "INCIDENT_CLOSED"
    LESSON_SAVED = "LESSON_SAVED"
    DEMO_RUN_STARTED = "DEMO_RUN_STARTED"


DECISION_KINDS = frozenset(
    {
        IncidentEventKind.REVIEW_DECIDED,
        IncidentEventKind.INCIDENT_RESOLVED,
        IncidentEventKind.LESSON_SAVED,
    }
)


class IncidentEvent(BaseModel):
    id: UUID
    incident_id: UUID | None
    investigation_id: UUID | None
    kind: IncidentEventKind
    occurred_at: datetime
    actor: str
    summary: str = Field(max_length=300)
    details: dict[str, Any] = Field(default_factory=dict)
    reconstructed: bool = False
    incident_title: str | None = None


class IncidentEventPage(BaseModel):
    events: list[IncidentEvent]
    next_before: str | None = None

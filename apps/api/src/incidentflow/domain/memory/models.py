from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from incidentflow.domain.investigations.models import utc_now


class IncidentLessonState(str, Enum):
    PENDING_INDEX = "PENDING_INDEX"
    CONFIRMED = "CONFIRMED"
    INDEX_FAILED = "INDEX_FAILED"


class IncidentLessonConfirmation(BaseModel):
    """The small, reviewed record eligible for long-term incident memory."""

    investigation_id: UUID
    service: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=100)
    confirmed_root_cause: str = Field(min_length=1, max_length=10_000)
    validated_resolution: str = Field(min_length=1, max_length=10_000)
    tenant_id: str | None = Field(default=None, max_length=200)


class IncidentLesson(IncidentLessonConfirmation):
    id: UUID = Field(default_factory=uuid4)
    state: IncidentLessonState = IncidentLessonState.PENDING_INDEX
    vector_id: str | None = None
    index_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    confirmed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

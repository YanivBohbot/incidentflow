from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class IncidentPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


def utc_now() -> datetime:
    return datetime.now(UTC)


class IncidentCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    priority: IncidentPriority = IncidentPriority.MEDIUM


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    priority: IncidentPriority
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IncidentUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=5,
        max_length=200,
    )
    description: str | None = Field(
        default=None,
        min_length=10,
        max_length=5000,
    )
    priority: IncidentPriority | None = None

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from incidentflow.agent.agents_specialist.contracts import InvestigationReport


class InvestigationLifecycle(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
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
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

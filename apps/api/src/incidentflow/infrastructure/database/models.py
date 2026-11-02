from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from incidentflow.domain.incidents.models import (
    IncidentPriority,
    IncidentStatus,
    utc_now,
)
from incidentflow.domain.investigations.models import InvestigationLifecycle
from incidentflow.domain.memory.models import IncidentLessonState
from incidentflow.infrastructure.database.base import Base


class IncidentORM(Base):
    __tablename__ = "incidents"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    priority: Mapped[IncidentPriority] = mapped_column(
        Enum(IncidentPriority, name="incident_priority"),
        nullable=False,
        default=IncidentPriority.MEDIUM,
    )

    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"),
        nullable=False,
        default=IncidentStatus.OPEN,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class InvestigationORM(Base):
    __tablename__ = "investigations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id"), nullable=False, index=True
    )
    incident_request: Mapped[str] = mapped_column(Text, nullable=False)
    incident_business_status: Mapped[str] = mapped_column(String(50), nullable=False)
    lifecycle: Mapped[InvestigationLifecycle] = mapped_column(
        Enum(InvestigationLifecycle, name="investigation_lifecycle"),
        nullable=False,
        default=InvestigationLifecycle.PENDING,
    )
    workflow_thread_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    report_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pending_human_review_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class IncidentLessonORM(Base):
    __tablename__ = "incident_lessons"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id"), nullable=False, index=True
    )
    service: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    confirmed_root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    validated_resolution: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[IncidentLessonState] = mapped_column(
        Enum(IncidentLessonState, name="incident_lesson_state"),
        nullable=False,
        default=IncidentLessonState.PENDING_INDEX,
    )
    vector_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )



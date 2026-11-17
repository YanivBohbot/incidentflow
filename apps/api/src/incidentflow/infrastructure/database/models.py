"""SQLAlchemy ORM tables.

Unique partial indexes allow one active investigation per incident and one open
incident per alarm, even across API instances.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from incidentflow.domain.incidents.models import (
    IncidentPriority,
    IncidentSource,
    IncidentStatus,
    utc_now,
)
from incidentflow.domain.investigations.models import InvestigationLifecycle
from incidentflow.domain.memory.models import IncidentLessonState
from incidentflow.infrastructure.database.base import Base

ACTIVE_INVESTIGATION_PREDICATE = "lifecycle IN ('PENDING', 'RUNNING')"

OPEN_STATUSES = (
    IncidentStatus.OPEN,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.PENDING_APPROVAL,
)
OPEN_INCIDENT_PREDICATE = (
    "external_id IS NOT NULL AND status IN "
    "(" + ", ".join(f"'{status.value}'" for status in OPEN_STATUSES) + ")"
)


class IncidentORM(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "uq_incidents_open_external",
            "source",
            "external_id",
            unique=True,
            postgresql_where=text(OPEN_INCIDENT_PREDICATE),
            sqlite_where=text(OPEN_INCIDENT_PREDICATE),
        ),
    )

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

    source: Mapped[IncidentSource] = mapped_column(
        Enum(IncidentSource, name="incident_source"),
        nullable=False,
        default=IncidentSource.MANUAL,
        server_default=IncidentSource.MANUAL.value,
    )

    service: Mapped[str | None] = mapped_column(String(200), nullable=True)

    external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

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
    __table_args__ = (
        Index(
            "uq_investigations_active_incident",
            "incident_id",
            unique=True,
            postgresql_where=text(ACTIVE_INVESTIGATION_PREDICATE),
            sqlite_where=text(ACTIVE_INVESTIGATION_PREDICATE),
        ),
    )

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
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pending_resume_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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


class IncidentEventORM(Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_time", "incident_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True
    )
    investigation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reconstructed: Mapped[bool] = mapped_column(nullable=False, default=False)


"""One-time reconstruction of incident events from data stored before the history existed.

Every row it writes is marked reconstructed: times come from created/updated timestamps and
the trace, so they are approximate, and the author of a resolution is unknown.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.incidents.models import IncidentStatus
from incidentflow.domain.investigations.models import (
    InvestigationLifecycle,
    InvestigationTraceStep,
)
from incidentflow.domain.memory.models import IncidentLessonState
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.models import (
    IncidentLessonORM,
    IncidentORM,
    InvestigationORM,
)

TraceReader = Callable[[UUID], list[InvestigationTraceStep]]
OPERATOR = re.compile(r"Operator \((?P<actor>.+)\)")
DECISIONS = {"REJECT": "Operator rejected", "REQUEST_INFORMATION": "more information"}


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _decision(step: InvestigationTraceStep) -> str:
    if step.status == "approved":
        return "APPROVE"
    return next((kind for kind, text in DECISIONS.items() if text in step.title), "REJECT")


class _Writer:
    def __init__(self, events: IncidentEventRepository, incident_id: UUID) -> None:
        self.events = events
        self.incident_id = incident_id
        self.count = 0

    def add(self, kind: IncidentEventKind, when: datetime, summary: str, **fields) -> None:
        self.events.record(
            kind,
            incident_id=self.incident_id,
            occurred_at=_utc(when),
            summary=summary,
            reconstructed=True,
            **fields,
        )
        self.count += 1


def _investigation_events(
    writer: _Writer, orm: InvestigationORM, trace_reader: TraceReader
) -> None:
    started = _utc(orm.created_at)
    common = {"investigation_id": orm.id}
    writer.add(IncidentEventKind.INVESTIGATION_STARTED, started, "Investigation started", **common)
    pause: InvestigationTraceStep | None = None
    for offset, step in enumerate(trace_reader(orm.id), start=1):
        when = started + timedelta(seconds=offset)
        if step.kind == "review_pause":
            pause = step
            details = {"review_type": step.data.get("review_type")}
            if step.data.get("tool_name"):
                details["tool_name"] = step.data["tool_name"]
            writer.add(
                IncidentEventKind.REVIEW_REQUESTED,
                when,
                "Paused for an operator decision",
                details=details,
                **common,
            )
        elif step.kind == "review_decision":
            match = OPERATOR.fullmatch(step.actor)
            actor = match.group("actor") if match else "unknown"
            details = {"decision": _decision(step), "reason": step.detail or None}
            if pause is not None and pause.data.get("tool_name"):
                details["tool_name"] = pause.data["tool_name"]
            writer.add(
                IncidentEventKind.REVIEW_DECIDED,
                when,
                f"{step.title} ({actor})",
                actor=actor,
                details=details,
                **common,
            )
    finished = _utc(orm.updated_at)
    if orm.lifecycle is InvestigationLifecycle.COMPLETED and orm.report_payload:
        report = orm.report_payload
        writer.add(
            IncidentEventKind.INVESTIGATION_COMPLETED,
            finished,
            f"Report written, confidence {round(report.get('confidence', 0) * 100)}%",
            details={
                "confidence": report.get("confidence"),
                "root_cause": report.get("root_cause"),
            },
            **common,
        )
    elif orm.lifecycle is InvestigationLifecycle.FAILED:
        writer.add(
            IncidentEventKind.INVESTIGATION_FAILED,
            finished,
            "Investigation failed",
            details={"error": orm.error_message},
            **common,
        )


def backfill(session: Session, *, trace_reader: TraceReader) -> int:
    """Reconstruct the journal of every incident that has no event yet; return rows written."""
    events = IncidentEventRepository(session)
    total = 0
    for incident in session.scalars(select(IncidentORM).order_by(IncidentORM.created_at)).all():
        if events.has_events_for_incident(incident.id):
            continue
        writer = _Writer(events, incident.id)
        writer.add(
            IncidentEventKind.INCIDENT_CREATED,
            incident.created_at,
            "Incident created",
            details={"source": incident.source.value},
        )
        investigations = session.scalars(
            select(InvestigationORM)
            .where(InvestigationORM.incident_id == incident.id)
            .order_by(InvestigationORM.created_at)
        ).all()
        for investigation in investigations:
            _investigation_events(writer, investigation, trace_reader)
        lessons = session.scalars(
            select(IncidentLessonORM).where(
                IncidentLessonORM.investigation_id.in_([item.id for item in investigations]),
                IncidentLessonORM.state == IncidentLessonState.CONFIRMED,
            )
        ).all()
        for lesson in lessons:
            writer.add(
                IncidentEventKind.LESSON_SAVED,
                lesson.confirmed_at or lesson.created_at,
                "Lesson saved to memory",
                investigation_id=lesson.investigation_id,
                details={"service": lesson.service},
            )
        if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
            resolved = incident.status is IncidentStatus.RESOLVED
            writer.add(
                IncidentEventKind.INCIDENT_RESOLVED
                if resolved
                else IncidentEventKind.INCIDENT_CLOSED,
                incident.updated_at,
                "Incident resolved" if resolved else "Incident closed",
                actor="unknown",
            )
        total += writer.count
    return total

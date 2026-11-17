"""Database access for incident events: the decision timeline and each incident's journal."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from incidentflow.domain.history.models import IncidentEvent, IncidentEventKind, IncidentEventPage
from incidentflow.infrastructure.database.models import IncidentEventORM, IncidentORM

MAX_PAGE_SIZE = 200


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def encode_cursor(event: IncidentEvent) -> str:
    """Opaque `before` cursor: the event's time and id, so equal times never skip rows."""
    return f"{event.occurred_at.isoformat()}|{event.id}"


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Parse a cursor from encode_cursor; raises ValueError when it is malformed."""
    moment, _, event_id = cursor.rpartition("|")
    return _utc(datetime.fromisoformat(moment)), UUID(event_id)


class IncidentEventRepository:
    """Append and read incident events; times are stored and returned in UTC."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        kind: IncidentEventKind,
        *,
        summary: str,
        incident_id: UUID | None = None,
        investigation_id: UUID | None = None,
        actor: str = "system",
        details: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
        reconstructed: bool = False,
    ) -> IncidentEvent:
        """Append one event and commit it."""
        orm = IncidentEventORM(
            kind=kind.value,
            incident_id=incident_id,
            investigation_id=investigation_id,
            actor=actor,
            summary=summary[:300],
            details=details or {},
            reconstructed=reconstructed,
        )
        if occurred_at is not None:
            orm.occurred_at = _utc(occurred_at)
        self.session.add(orm)
        self.session.commit()
        self.session.refresh(orm)
        return self._to_domain(orm)

    def list_history(
        self,
        *,
        incident_id: UUID | None = None,
        kinds: Iterable[IncidentEventKind] | None = None,
        before: str | None = None,
        limit: int = 50,
    ) -> IncidentEventPage:
        """Return events newest first with their incident title, one page at a time."""
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        statement = select(IncidentEventORM, IncidentORM.title).outerjoin(
            IncidentORM, IncidentORM.id == IncidentEventORM.incident_id
        )
        if incident_id is not None:
            statement = statement.where(IncidentEventORM.incident_id == incident_id)
        if kinds:
            statement = statement.where(IncidentEventORM.kind.in_([kind.value for kind in kinds]))
        if before:
            moment, event_id = decode_cursor(before)
            statement = statement.where(
                or_(
                    IncidentEventORM.occurred_at < moment,
                    and_(IncidentEventORM.occurred_at == moment, IncidentEventORM.id < event_id),
                )
            )
        statement = statement.order_by(
            IncidentEventORM.occurred_at.desc(), IncidentEventORM.id.desc()
        ).limit(limit + 1)
        rows = self.session.execute(statement).all()
        events = [self._to_domain(orm, title) for orm, title in rows[:limit]]
        next_before = encode_cursor(events[-1]) if len(rows) > limit else None
        return IncidentEventPage(events=events, next_before=next_before)

    def list_for_incident(self, incident_id: UUID) -> list[IncidentEvent]:
        """Return one incident's journal, oldest first."""
        statement = (
            select(IncidentEventORM, IncidentORM.title)
            .outerjoin(IncidentORM, IncidentORM.id == IncidentEventORM.incident_id)
            .where(IncidentEventORM.incident_id == incident_id)
            .order_by(IncidentEventORM.occurred_at, IncidentEventORM.id)
        )
        return [self._to_domain(orm, title) for orm, title in self.session.execute(statement)]

    def has_events_for_incident(self, incident_id: UUID) -> bool:
        statement = select(IncidentEventORM.id).where(IncidentEventORM.incident_id == incident_id)
        return self.session.scalars(statement.limit(1)).first() is not None

    def has_event(self, investigation_id: UUID, kind: IncidentEventKind, **details: Any) -> bool:
        """Whether this investigation already has an event of this kind with these details."""
        statement = select(IncidentEventORM).where(
            IncidentEventORM.investigation_id == investigation_id,
            IncidentEventORM.kind == kind.value,
        )
        return any(
            all(orm.details.get(key) == value for key, value in details.items())
            for orm in self.session.scalars(statement)
        )

    @staticmethod
    def _to_domain(orm: IncidentEventORM, title: str | None = None) -> IncidentEvent:
        return IncidentEvent(
            id=orm.id,
            incident_id=orm.incident_id,
            investigation_id=orm.investigation_id,
            kind=IncidentEventKind(orm.kind),
            occurred_at=_utc(orm.occurred_at),
            actor=orm.actor,
            summary=orm.summary,
            details=dict(orm.details or {}),
            reconstructed=orm.reconstructed,
            incident_title=title,
        )

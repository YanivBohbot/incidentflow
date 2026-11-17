"""Database access for incidents."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from incidentflow.domain.incidents.models import (
    AlarmIncidentCreate,
    Incident,
    IncidentCreate,
    IncidentSource,
    IncidentStatus,
    IncidentUpdate,
)
from incidentflow.infrastructure.database.models import OPEN_STATUSES, IncidentORM


class DuplicateOpenIncidentError(Exception):
    """An open incident already exists for the same source and external id."""


class IncidentRepository:
    """Read and write incidents; timestamps are always stored in UTC."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def to_domain(orm: IncidentORM) -> Incident:
        return Incident.model_validate(
            {
                "id": orm.id,
                "title": orm.title,
                "description": orm.description,
                "priority": orm.priority,
                "status": orm.status,
                "source": orm.source,
                "service": orm.service,
                "external_id": orm.external_id,
                "created_at": orm.created_at,
                "updated_at": orm.updated_at,
            }
        )

    def create_incident(
        self,
        data: IncidentCreate,
    ) -> Incident:
        orm = IncidentORM(
            title=data.title,
            description=data.description,
            priority=data.priority,
        )

        self.session.add(orm)
        self.session.commit()
        self.session.refresh(orm)

        return self.to_domain(orm)

    def create_alarm_incident(self, data: AlarmIncidentCreate) -> Incident:
        orm = IncidentORM(
            title=data.title,
            description=data.description,
            priority=data.priority,
            source=IncidentSource.CLOUDWATCH_ALARM,
            service=data.service,
            external_id=data.external_id,
        )

        self.session.add(orm)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DuplicateOpenIncidentError(data.external_id) from error
        self.session.refresh(orm)

        return self.to_domain(orm)

    def close_open_alarm_incidents(self, alarm_names: Sequence[str]) -> int:
        """Close the open incidents of the given alarms."""
        if not alarm_names:
            return 0

        statement = select(IncidentORM).where(
            IncidentORM.source == IncidentSource.CLOUDWATCH_ALARM,
            IncidentORM.status.in_(OPEN_STATUSES),
            IncidentORM.external_id.is_not(None),
        )
        suffixes = tuple(f":alarm:{name}" for name in alarm_names)
        closed = 0
        for orm in self.session.scalars(statement):
            if orm.external_id is not None and orm.external_id.endswith(suffixes):
                orm.status = IncidentStatus.CLOSED
                closed += 1

        if closed:
            self.session.commit()

        return closed

    def list_open_alarm_incident_ids(self, alarm_names: Sequence[str]) -> list[UUID]:
        if not alarm_names:
            return []

        statement = select(IncidentORM.id, IncidentORM.external_id).where(
            IncidentORM.source == IncidentSource.CLOUDWATCH_ALARM,
            IncidentORM.status.in_(OPEN_STATUSES),
            IncidentORM.external_id.is_not(None),
        )
        suffixes = tuple(f":alarm:{name}" for name in alarm_names)
        return [
            incident_id
            for incident_id, external_id in self.session.execute(statement)
            if external_id is not None and external_id.endswith(suffixes)
        ]

    def latest_alarm_incident_created_at(self, alarm_names: Sequence[str]) -> datetime | None:
        """Return when the newest incident of the given alarms was created."""
        if not alarm_names:
            return None

        statement = select(IncidentORM.external_id, IncidentORM.created_at).where(
            IncidentORM.source == IncidentSource.CLOUDWATCH_ALARM,
            IncidentORM.external_id.is_not(None),
        )
        suffixes = tuple(f":alarm:{name}" for name in alarm_names)
        matching = [
            created_at
            for external_id, created_at in self.session.execute(statement)
            if external_id is not None and external_id.endswith(suffixes)
        ]
        if not matching:
            return None

        latest = max(matching)
        return latest if latest.tzinfo else latest.replace(tzinfo=UTC)

    def get_incident(
        self,
        incident_id: UUID,
    ) -> Incident | None:
        orm = self.session.get(IncidentORM, incident_id)

        if orm is None:
            return None

        return self.to_domain(orm)

    def list_incidents(self) -> list[Incident]:
        statement = select(IncidentORM).order_by(IncidentORM.created_at.desc())

        incidents = self.session.scalars(statement).all()

        return [self.to_domain(orm) for orm in incidents]

    def update_incident(
        self,
        incident_id: UUID,
        data: IncidentUpdate,
    ) -> Incident | None:
        orm = self.session.get(IncidentORM, incident_id)

        if orm is None:
            return None

        changes = data.model_dump(exclude_unset=True)

        for field, value in changes.items():
            setattr(orm, field, value)

        if changes:
            self.session.commit()
            self.session.refresh(orm)

        return self.to_domain(orm)

    def resolve_incident(self, incident_id: UUID) -> Incident | None:
        """Mark the incident RESOLVED; it then leaves the open queue and its counts."""
        orm = self.session.get(IncidentORM, incident_id)
        if orm is None:
            return None
        if orm.status is not IncidentStatus.RESOLVED:
            orm.status = IncidentStatus.RESOLVED
            self.session.commit()
            self.session.refresh(orm)
        return self.to_domain(orm)

    def delete_incident(
        self,
        incident_id: UUID,
    ) -> bool:
        orm = self.session.get(IncidentORM, incident_id)

        if orm is None:
            return False

        self.session.delete(orm)
        self.session.commit()

        return True

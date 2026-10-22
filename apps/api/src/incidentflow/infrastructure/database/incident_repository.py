from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from incidentflow.domain.incidents.models import (
    Incident,
    IncidentCreate,
    IncidentUpdate,
)
from incidentflow.infrastructure.database.models import IncidentORM


class IncidentRepository:
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

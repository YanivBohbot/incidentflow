from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationLifecycle,
)
from incidentflow.infrastructure.database.models import InvestigationORM


class InvestigationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def to_domain(orm: InvestigationORM) -> Investigation:
        report = (
            InvestigationReport.model_validate(orm.report_payload)
            if orm.report_payload is not None
            else None
        )
        return Investigation.model_validate(
            {
                "id": orm.id,
                "incident_id": orm.incident_id,
                "incident_request": orm.incident_request,
                "incident_business_status": orm.incident_business_status,
                "lifecycle": orm.lifecycle,
                "workflow_thread_id": orm.workflow_thread_id,
                "report": report,
                "error_message": orm.error_message,
                "created_at": orm.created_at,
                "updated_at": orm.updated_at,
            }
        )

    def create_investigation(self, data: InvestigationCreate) -> Investigation:
        investigation_id = uuid4()
        orm = InvestigationORM(
            id=investigation_id,
            incident_id=data.incident_id,
            incident_request=data.incident_request,
            incident_business_status=data.incident_business_status,
            workflow_thread_id=f"investigation:{investigation_id}",
        )
        self.session.add(orm)
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def get_investigation(self, investigation_id: UUID) -> Investigation | None:
        orm = self.session.get(InvestigationORM, investigation_id)
        if orm is None:
            return None
        return self.to_domain(orm)

    def list_for_incident(self, incident_id: UUID) -> list[Investigation]:
        statement = (
            select(InvestigationORM)
            .where(InvestigationORM.incident_id == incident_id)
            .order_by(InvestigationORM.created_at.desc())
        )
        return [self.to_domain(orm) for orm in self.session.scalars(statement).all()]

    def list_investigations(self) -> list[Investigation]:
        statement = select(InvestigationORM).order_by(InvestigationORM.created_at.desc())
        return [self.to_domain(orm) for orm in self.session.scalars(statement).all()]

    def mark_running(self, investigation_id: UUID) -> Investigation | None:
        orm = self.session.get(InvestigationORM, investigation_id)
        if orm is None:
            return None

        orm.lifecycle = InvestigationLifecycle.RUNNING
        orm.error_message = None
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def complete_investigation(
        self, investigation_id: UUID, report: InvestigationReport
    ) -> Investigation | None:
        orm = self.session.get(InvestigationORM, investigation_id)
        if orm is None:
            return None

        orm.lifecycle = InvestigationLifecycle.COMPLETED
        orm.report_payload = report.model_dump(mode="json")
        orm.error_message = None
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def fail_investigation(
        self, investigation_id: UUID, error_message: str
    ) -> Investigation | None:
        orm = self.session.get(InvestigationORM, investigation_id)
        if orm is None:
            return None

        orm.lifecycle = InvestigationLifecycle.FAILED
        orm.error_message = error_message
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

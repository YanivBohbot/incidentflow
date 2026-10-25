from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import (
    InvestigationCreate,
    InvestigationLifecycle,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM


class CompletedWorkflow:
    def __init__(self, report: InvestigationReport) -> None:
        self.report = report

    def invoke(self, payload: dict, config: dict) -> dict:
        assert payload["incident_request"] == "Investigate Payment API HTTP 500 errors."
        assert config["configurable"]["thread_id"].startswith("investigation:")
        return {
            "investigation_lifecycle": "completed",
            "report": self.report,
            "errors": [],
        }


class FailedWorkflow:
    def invoke(self, payload: dict, config: dict) -> dict:
        return {
            "investigation_lifecycle": "failed",
            "report": None,
            "errors": ["incident_request must not be empty."],
        }


def create_incident(session: Session) -> IncidentORM:
    incident = IncidentORM(
        id=uuid4(),
        title="Payment API failures",
        description="Payment API has returned HTTP 500 errors since this morning.",
        priority=IncidentPriority.HIGH,
    )
    session.add(incident)
    session.commit()
    return incident


def test_service_persists_a_completed_workflow_report() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = create_incident(session)
        report = InvestigationReport(
            summary="Database pool exhaustion is suspected.",
            agents_consulted=["data_intelligence_agent"],
            evidence=[],
            hypotheses=["Connection pool exhaustion."],
            proposed_actions=["Request approval before mitigation."],
            limitations=["Sources are simulated."],
            confidence=0.8,
        )
        service = InvestigationService(
            InvestigationRepository(session),
            IncidentRepository(session),
            CompletedWorkflow(report),
        )

        investigation = service.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert investigation.lifecycle == InvestigationLifecycle.COMPLETED
        assert investigation.report == report


def test_service_persists_a_failed_workflow() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = create_incident(session)
        service = InvestigationService(
            InvestigationRepository(session),
            IncidentRepository(session),
            FailedWorkflow(),
        )

        investigation = service.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert investigation.lifecycle == InvestigationLifecycle.FAILED
        assert investigation.error_message == "incident_request must not be empty."

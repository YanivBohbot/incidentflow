from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.agent.findings import InvestigationReport
from incidentflow.application.services.investigation_recovery import (
    INTERRUPTED_RUN_MESSAGE,
    recover_interrupted_investigations,
)
from incidentflow.domain.incidents.models import IncidentCreate
from incidentflow.domain.investigations.models import InvestigationCreate, InvestigationLifecycle
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)


def test_startup_recovery_fails_only_investigations_left_running() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        incident = IncidentRepository(session).create_incident(
            IncidentCreate(title="Payment errors", description="HTTP 500 on POST /payments")
        )
        repository = InvestigationRepository(session)
        create = InvestigationCreate(
            incident_id=incident.id,
            incident_request="Investigate",
            incident_business_status="OPEN",
        )
        stuck = repository.mark_running(repository.create_investigation(create).id)
        done = repository.create_investigation(create)
        repository.complete_investigation(
            done.id, InvestigationReport(summary="ok", confidence=0.5)
        )

    assert recover_interrupted_investigations(factory) == 1
    assert recover_interrupted_investigations(factory) == 0  # idempotent

    with factory() as session:
        repository = InvestigationRepository(session)
        recovered = repository.get_investigation(stuck.id)
        assert recovered.lifecycle is InvestigationLifecycle.FAILED
        assert recovered.error_message == INTERRUPTED_RUN_MESSAGE
        assert repository.get_investigation(done.id).lifecycle is InvestigationLifecycle.COMPLETED

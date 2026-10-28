from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.application.services.incident_lesson_service import IncidentLessonService
from incidentflow.domain.investigations.models import InvestigationLifecycle
from incidentflow.domain.memory.models import (
    IncidentLessonConfirmation,
    IncidentLessonState,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_lesson_repository import IncidentLessonRepository
from incidentflow.infrastructure.database.models import InvestigationORM


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _investigation(session: Session, lifecycle: InvestigationLifecycle) -> InvestigationORM:
    investigation = InvestigationORM(
        incident_id=uuid4(),
        incident_request="Investigate Payment API errors.",
        incident_business_status="OPEN",
        lifecycle=lifecycle,
        workflow_thread_id=f"investigation:{uuid4()}",
    )
    session.add(investigation)
    session.commit()
    session.refresh(investigation)
    return investigation


def _confirmation(investigation_id):
    return IncidentLessonConfirmation(
        investigation_id=investigation_id,
        service="payment-api",
        environment="production",
        confirmed_root_cause="MongoDB connection pool exhaustion.",
        validated_resolution="Increase pool capacity and reduce long-running queries.",
    )


def test_only_completed_investigations_create_pending_index_lessons() -> None:
    session = _session()
    repository = IncidentLessonRepository(session)

    failed_investigation = _investigation(session, InvestigationLifecycle.FAILED)
    with pytest.raises(ValueError, match="completed investigation"):
        repository.create_pending(_confirmation(failed_investigation.id))

    completed_investigation = _investigation(session, InvestigationLifecycle.COMPLETED)
    lesson = repository.create_pending(_confirmation(completed_investigation.id))

    assert lesson.investigation_id == completed_investigation.id
    assert lesson.state is IncidentLessonState.PENDING_INDEX
    assert lesson.index_error is None


def test_failed_pinecone_index_does_not_mark_lesson_confirmed() -> None:
    class FailingIndex:
        def index_confirmed_incident_lesson(self, _lesson) -> str:
            raise RuntimeError("Pinecone unavailable")

    session = _session()
    repository = IncidentLessonRepository(session)
    investigation = _investigation(session, InvestigationLifecycle.COMPLETED)
    service = IncidentLessonService(repository, FailingIndex())

    index_failed = service.confirm_and_index(_confirmation(investigation.id))
    confirmed = repository.mark_confirmed(index_failed.id, "resolved-incident:123")

    assert index_failed is not None
    assert index_failed.state is IncidentLessonState.INDEX_FAILED
    assert index_failed.index_error == "Pinecone unavailable"
    assert confirmed is None


def test_successful_pinecone_index_marks_lesson_confirmed() -> None:
    class SuccessfulIndex:
        def index_confirmed_incident_lesson(self, _lesson) -> str:
            return "resolved-incident:123"

    session = _session()
    repository = IncidentLessonRepository(session)
    investigation = _investigation(session, InvestigationLifecycle.COMPLETED)
    service = IncidentLessonService(repository, SuccessfulIndex())

    confirmed = service.confirm_and_index(_confirmation(investigation.id))

    assert confirmed.state is IncidentLessonState.CONFIRMED
    assert confirmed.vector_id == "resolved-incident:123"
    assert confirmed.confirmed_at is not None

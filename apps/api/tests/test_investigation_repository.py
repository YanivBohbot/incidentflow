from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import HumanReview, HumanReviewType
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import (
    InvestigationCreate,
    InvestigationLifecycle,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM


def test_repository_creates_and_completes_an_investigation() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = IncidentORM(
            id=uuid4(),
            title="Payment API failures",
            description="Payment API has returned HTTP 500 errors since this morning.",
            priority=IncidentPriority.HIGH,
        )
        session.add(incident)
        session.commit()

        repository = InvestigationRepository(session)
        investigation = repository.create_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert investigation.lifecycle == InvestigationLifecycle.PENDING
        assert investigation.workflow_thread_id == f"investigation:{investigation.id}"

        report = InvestigationReport(
            summary="Database pool exhaustion is suspected.",
            agents_consulted=["data_intelligence_agent"],
            evidence=[],
            hypotheses=["Connection pool exhaustion."],
            proposed_actions=["Request approval before mitigation."],
            limitations=["Sources are simulated."],
            confidence=0.8,
        )
        completed = repository.complete_investigation(investigation.id, report)

        assert completed is not None
        assert completed.lifecycle == InvestigationLifecycle.COMPLETED
        assert completed.report == report


def test_repository_persists_a_pending_human_review() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = IncidentORM(
            id=uuid4(),
            title="Payment API failures",
            description="Payment API has returned HTTP 500 errors since this morning.",
            priority=IncidentPriority.HIGH,
        )
        session.add(incident)
        session.commit()
        repository = InvestigationRepository(session)
        investigation = repository.create_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )
        report = InvestigationReport(summary="Review needed.", confidence=0.8)
        review = HumanReview(
            review_type=HumanReviewType.INSUFFICIENT_EVIDENCE,
            reason="An operator must provide the missing deployment identifier.",
            evidence_references=["mongodb:event-17"],
        )

        awaiting = repository.mark_awaiting_human_review(investigation.id, report, review)

        assert awaiting is not None
        assert awaiting.lifecycle is InvestigationLifecycle.AWAITING_HUMAN_REVIEW
        assert awaiting.report == report
        assert awaiting.human_review == review

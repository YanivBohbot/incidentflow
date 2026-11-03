from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from incidentflow.agent.findings import InvestigationReport
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewType,
)
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

    async def ainvoke(self, payload: dict, config: dict) -> dict:
        assert payload["incident_request"] == "Investigate Payment API HTTP 500 errors."
        assert config["configurable"]["thread_id"].startswith("investigation:")
        return {
            "investigation_lifecycle": "completed",
            "report": self.report,
            "errors": [],
        }


class FailedWorkflow:
    async def ainvoke(self, payload: dict, config: dict) -> dict:
        return {
            "investigation_lifecycle": "failed",
            "report": None,
            "errors": ["incident_request must not be empty."],
        }


class ThrowingWorkflow:
    async def ainvoke(self, payload: dict, config: dict) -> dict:
        raise RuntimeError("Specialist integration became unavailable.")


class PausingThenCompletingWorkflow:
    """Simulate one interruption and verify that the same graph thread resumes."""

    def __init__(self, report: InvestigationReport, review: HumanReview) -> None:
        self.report = report
        self.review = review
        self.thread_ids: list[str] = []

    async def ainvoke(self, payload: object, config: dict) -> dict:
        self.thread_ids.append(config["configurable"]["thread_id"])
        if len(self.thread_ids) == 1:
            return {
                "__interrupt__": [object()],
                "report": self.report,
                "human_review": self.review,
                "errors": [],
            }
        return {
            "investigation_lifecycle": "completed",
            "report": self.report,
            "errors": [],
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


@pytest.mark.anyio
async def test_service_persists_a_completed_workflow_report() -> None:
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

        investigation = await service.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert investigation.lifecycle == InvestigationLifecycle.COMPLETED
        assert investigation.report == report


@pytest.mark.anyio
async def test_service_persists_a_failed_workflow() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = create_incident(session)
        service = InvestigationService(
            InvestigationRepository(session),
            IncidentRepository(session),
            FailedWorkflow(),
        )

        investigation = await service.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert investigation.lifecycle == InvestigationLifecycle.FAILED
        assert investigation.error_message == "incident_request must not be empty."


@pytest.mark.anyio
async def test_service_returns_a_persisted_failure_when_workflow_raises() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = create_incident(session)
        service = InvestigationService(
            InvestigationRepository(session),
            IncidentRepository(session),
            ThrowingWorkflow(),
        )

        investigation = await service.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert investigation.lifecycle == InvestigationLifecycle.FAILED
        assert investigation.error_message == "Workflow execution failed before a report was produced."


@pytest.mark.anyio
async def test_service_persists_pause_and_resumes_the_same_workflow_thread() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        incident = create_incident(session)
        report = InvestigationReport(summary="A human decision is required.", confidence=0.8)
        review = HumanReview(
            review_type=HumanReviewType.JIRA_WRITE,
            reason="A Jira issue would communicate the confirmed impact.",
            evidence_references=["mongodb:event-17"],
            draft={"summary": "Payment API incident"},
        )
        workflow = PausingThenCompletingWorkflow(report, review)
        service = InvestigationService(
            InvestigationRepository(session),
            IncidentRepository(session),
            workflow,
        )

        paused = await service.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate Payment API HTTP 500 errors.",
                incident_business_status="OPEN",
            )
        )

        assert paused.lifecycle == InvestigationLifecycle.AWAITING_HUMAN_REVIEW
        assert paused.human_review == review

        completed = await service.resume_human_review(
            paused.id,
            HumanReviewDecision(decision="REJECT", actor="on-call-operator"),
        )

        assert completed is not None
        assert completed.lifecycle == InvestigationLifecycle.COMPLETED
        assert workflow.thread_ids == [paused.workflow_thread_id, paused.workflow_thread_id]

import asyncio
from collections.abc import Iterator
from uuid import UUID

from agent_fakes import ApprovalGatedSupervisor
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.agent.findings import (
    InvestigationEvidence,
    InvestigationReport,
)
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)
from incidentflow.api.routes.incidents import (
    get_incident_service,
)
from incidentflow.api.routes.incidents import (
    router as incidents_router,
)
from incidentflow.api.routes.investigations import (
    get_investigation_service,
    get_job_queue,
)
from incidentflow.api.routes.investigations import (
    router as investigations_router,
)
from incidentflow.application.jobs.processor import InvestigationJobProcessor
from incidentflow.application.jobs.queue import InMemoryJobQueue
from incidentflow.application.services.incident_service import IncidentService
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)


class CompletedSupervisor:
    def __init__(self, report: InvestigationReport) -> None:
        self.report = report

    async def ainvoke(self, _payload: dict, *, config: dict) -> dict:
        return {"structured_response": self.report}


def test_incident_investigation_and_persisted_report_round_trip() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    report = InvestigationReport(
        summary="Database pool saturation is supported by the observed evidence.",
        agents_consulted=["data_intelligence_agent", "knowledge_agent"],
        evidence=[
            InvestigationEvidence(
                source="operational_events",
                detail="Active database connections reached the configured limit.",
                source_status="live",
            )
        ],
        hypotheses=["Database pool saturation causes request timeouts."],
        proposed_actions=["Request approval before changing connection settings."],
        limitations=["This test uses a deterministic workflow double."],
        confidence=0.8,
    )
    queue = InMemoryJobQueue()
    workflow = build_investigation_workflow(
        CompletedSupervisor(report), checkpointer=InMemorySaver()
    )
    processor = InvestigationJobProcessor(
        session_factory, workflow, lease_seconds=60, max_attempts=3
    )

    def incident_service() -> Iterator[IncidentService]:
        with session_factory() as session:
            yield IncidentService(IncidentRepository(session))

    def investigation_service() -> Iterator[InvestigationService]:
        with session_factory() as session:
            yield InvestigationService(
                InvestigationRepository(session), IncidentRepository(session), queue, workflow
            )

    app = FastAPI()
    app.include_router(incidents_router, prefix="/api")
    app.include_router(investigations_router, prefix="/api")
    app.dependency_overrides[get_incident_service] = incident_service
    app.dependency_overrides[get_investigation_service] = investigation_service
    app.dependency_overrides[get_job_queue] = lambda: queue

    with TestClient(app) as client:
        incident_response = client.post(
            "/api/incidents",
            json={
                "title": "Payment API failures",
                "description": "Payment API returned repeated HTTP 500 responses.",
                "priority": "HIGH",
            },
        )
        assert incident_response.status_code == 201
        incident_id = incident_response.json()["id"]

        investigation_response = client.post(
            "/api/investigations",
            json={
                "incident_id": incident_id,
                "incident_request": "Investigate Payment API HTTP 500 errors.",
            },
        )
        assert investigation_response.status_code == 202
        created = investigation_response.json()
        assert created["lifecycle"] == "PENDING"
        assert queue.sent == [UUID(created["id"])]

        duplicate = client.post(
            "/api/investigations",
            json={
                "incident_id": incident_id,
                "incident_request": "Investigate Payment API HTTP 500 errors.",
            },
        )
        assert duplicate.status_code == 409

        asyncio.run(processor.process(UUID(created["id"])))

        persisted_response = client.get(f"/api/investigations/{created['id']}")
        assert persisted_response.status_code == 200
        persisted = persisted_response.json()
        assert persisted["lifecycle"] == "COMPLETED"
        assert persisted["report"]["evidence"][0]["source_status"] == "live"


def test_api_resumes_a_manual_supervisor_call_after_jira_hitl() -> None:
    """Exercise HTTP, database, workflow, manual Supervisor call, interrupt, and resume."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    supervisor = ApprovalGatedSupervisor(
        InvestigationReport(summary="A Jira issue was considered after the review.", confidence=0.8)
    )
    workflow = build_investigation_workflow(supervisor, checkpointer=InMemorySaver())
    queue = InMemoryJobQueue()
    processor = InvestigationJobProcessor(
        session_factory, workflow, lease_seconds=60, max_attempts=3
    )

    def incident_service() -> Iterator[IncidentService]:
        with session_factory() as session:
            yield IncidentService(IncidentRepository(session))

    def investigation_service() -> Iterator[InvestigationService]:
        with session_factory() as session:
            yield InvestigationService(
                InvestigationRepository(session), IncidentRepository(session), queue, workflow
            )

    app = FastAPI()
    app.include_router(incidents_router, prefix="/api")
    app.include_router(investigations_router, prefix="/api")
    app.dependency_overrides[get_incident_service] = incident_service
    app.dependency_overrides[get_investigation_service] = investigation_service
    app.dependency_overrides[get_job_queue] = lambda: queue

    with TestClient(app) as client:
        incident_response = client.post(
            "/api/incidents",
            json={
                "title": "Payment API failures",
                "description": "Payment API returned HTTP 500 responses.",
                "priority": "HIGH",
            },
        )
        investigation_response = client.post(
            "/api/investigations",
            json={
                "incident_id": incident_response.json()["id"],
                "incident_request": "Investigate Payment API HTTP 500 errors.",
            },
        )
        assert investigation_response.status_code == 202
        started = investigation_response.json()
        assert started["lifecycle"] == "PENDING"
        asyncio.run(processor.process(UUID(started["id"])))
        paused = client.get(f"/api/investigations/{started['id']}").json()
        assert paused["lifecycle"] == "AWAITING_HUMAN_REVIEW"
        assert paused["human_review"]["review_type"] == "JIRA_WRITE"
        assert paused["human_review"]["draft"]["tool_name"] == "createJiraIssue"

        resumed_response = client.post(
            f"/api/investigations/{paused['id']}/human-review/resolve",
            json={"decision": "APPROVE", "actor": "test-operator"},
        )
        assert resumed_response.status_code == 202
        assert resumed_response.json()["lifecycle"] == "PENDING"
        asyncio.run(processor.process(UUID(paused["id"])))
        completed = client.get(f"/api/investigations/{paused['id']}").json()
        assert completed["lifecycle"] == "COMPLETED"

    assert supervisor.resume_values == [{"decisions": [{"type": "approve"}]}]

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.agent.agents_specialist.contracts import (
    InvestigationEvidence,
    InvestigationReport,
)
from incidentflow.api.routes.incidents import (
    get_incident_service,
)
from incidentflow.api.routes.incidents import (
    router as incidents_router,
)
from incidentflow.api.routes.investigations import (
    get_investigation_service,
)
from incidentflow.api.routes.investigations import (
    router as investigations_router,
)
from incidentflow.application.services.incident_service import IncidentService
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)


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

    def incident_service() -> Iterator[IncidentService]:
        with session_factory() as session:
            yield IncidentService(IncidentRepository(session))

    def investigation_service() -> Iterator[InvestigationService]:
        with session_factory() as session:
            yield InvestigationService(
                InvestigationRepository(session),
                IncidentRepository(session),
                CompletedWorkflow(report),
            )

    app = FastAPI()
    app.include_router(incidents_router, prefix="/api")
    app.include_router(investigations_router, prefix="/api")
    app.dependency_overrides[get_incident_service] = incident_service
    app.dependency_overrides[get_investigation_service] = investigation_service

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
        assert investigation_response.status_code == 201
        created = investigation_response.json()
        assert created["lifecycle"] == "COMPLETED"
        assert created["report"]["evidence"][0]["source_status"] == "live"

        persisted_response = client.get(f"/api/investigations/{created['id']}")
        assert persisted_response.status_code == 200
        assert persisted_response.json()["report"] == created["report"]

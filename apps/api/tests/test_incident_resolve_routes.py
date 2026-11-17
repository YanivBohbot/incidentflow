from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.api.routes.incidents import get_incident_service
from incidentflow.api.routes.incidents import router as incidents_router
from incidentflow.application.services.incident_service import IncidentService
from incidentflow.core.auth import LOCAL_PRINCIPAL, Principal, get_principal
from incidentflow.domain.incidents.models import IncidentCreate, IncidentStatus
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository


@pytest.fixture
def repository() -> Iterator[IncidentRepository]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield IncidentRepository(session)


def build_client(repository: IncidentRepository, principal: Principal) -> TestClient:
    app = FastAPI()
    app.include_router(incidents_router, prefix="/api")
    app.dependency_overrides[get_incident_service] = lambda: IncidentService(repository)
    app.dependency_overrides[get_principal] = lambda: principal
    return TestClient(app)


def create_incident(repository: IncidentRepository):
    return repository.create_incident(
        IncidentCreate(title="Checkout down", description="checkout-api returns HTTP 503.")
    )


def test_operator_marks_an_incident_resolved(repository: IncidentRepository) -> None:
    incident = create_incident(repository)

    response = build_client(repository, LOCAL_PRINCIPAL).post(
        f"/api/incidents/{incident.id}/resolve"
    )

    assert response.status_code == 200
    assert response.json()["status"] == IncidentStatus.RESOLVED.value
    assert repository.get_incident(incident.id).status is IncidentStatus.RESOLVED


def test_resolving_a_missing_incident_is_404(repository: IncidentRepository) -> None:
    response = build_client(repository, LOCAL_PRINCIPAL).post(f"/api/incidents/{uuid4()}/resolve")

    assert response.status_code == 404


def test_a_viewer_cannot_resolve_an_incident(repository: IncidentRepository) -> None:
    incident = create_incident(repository)
    viewer = Principal("viewer", frozenset({"viewer"}))

    response = build_client(repository, viewer).post(f"/api/incidents/{incident.id}/resolve")

    assert response.status_code == 403
    assert repository.get_incident(incident.id).status is IncidentStatus.OPEN

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.api.routes.history import get_event_repository
from incidentflow.api.routes.history import router as history_router
from incidentflow.core.auth import Principal, get_principal
from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.incidents.models import IncidentCreate
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
VIEWER = Principal("viewer", frozenset({"viewer"}))


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(history_router, prefix="/api")
    app.dependency_overrides[get_event_repository] = lambda: IncidentEventRepository(session)
    app.dependency_overrides[get_principal] = lambda: VIEWER
    return TestClient(app)


@pytest.fixture
def incident(session: Session):
    created = IncidentRepository(session).create_incident(
        IncidentCreate(title="Checkout down", description="checkout-api returns HTTP 503.")
    )
    events = IncidentEventRepository(session)
    for minutes, kind in enumerate(
        [
            IncidentEventKind.INCIDENT_CREATED,
            IncidentEventKind.INVESTIGATION_STARTED,
            IncidentEventKind.REVIEW_DECIDED,
            IncidentEventKind.INCIDENT_RESOLVED,
        ]
    ):
        events.record(
            kind,
            incident_id=created.id,
            summary=kind.value,
            occurred_at=T0 + timedelta(minutes=minutes),
        )
    return created


def test_viewer_reads_history_newest_first(client, incident) -> None:
    response = client.get("/api/history")

    assert response.status_code == 200
    body = response.json()
    assert [item["kind"] for item in body["events"]] == [
        "INCIDENT_RESOLVED",
        "REVIEW_DECIDED",
        "INVESTIGATION_STARTED",
        "INCIDENT_CREATED",
    ]
    assert body["events"][0]["incident_title"] == "Checkout down"


def test_history_filters_and_paginates(client, incident) -> None:
    decisions = client.get(
        "/api/history", params={"kinds": "REVIEW_DECIDED,INCIDENT_RESOLVED"}
    ).json()
    first = client.get("/api/history", params={"limit": 3}).json()
    rest = client.get("/api/history", params={"limit": 3, "before": first["next_before"]}).json()

    assert [item["kind"] for item in decisions["events"]] == [
        "INCIDENT_RESOLVED",
        "REVIEW_DECIDED",
    ]
    assert len(first["events"]) == 3
    assert [item["kind"] for item in rest["events"]] == ["INCIDENT_CREATED"]
    assert rest["next_before"] is None


def test_unknown_kind_is_422(client, incident) -> None:
    assert client.get("/api/history", params={"kinds": "NOT_A_KIND"}).status_code == 422
    assert client.get("/api/history", params={"before": "garbage"}).status_code == 422


def test_incident_journal_route_and_404(client, incident) -> None:
    journal = client.get(f"/api/incidents/{incident.id}/events")

    assert journal.status_code == 200
    assert journal.json()[0]["kind"] == "INCIDENT_CREATED"
    assert client.get(f"/api/incidents/{uuid4()}/events").status_code == 404

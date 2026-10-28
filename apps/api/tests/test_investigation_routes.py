from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from incidentflow.api.routes.investigations import (
    get_investigation_service,
    router,
)
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationLifecycle,
)


class FakeInvestigationService:
    def __init__(self) -> None:
        self.investigation_id = uuid4()

    def start_investigation(self, data):
        if data.incident_id == UUID("00000000-0000-0000-0000-000000000000"):
            return None
        return Investigation(
            id=self.investigation_id,
            incident_id=data.incident_id,
            incident_request=data.incident_request,
            incident_business_status="OPEN",
            lifecycle=InvestigationLifecycle.COMPLETED,
            workflow_thread_id=f"investigation:{self.investigation_id}",
        )

    def get_investigation(self, investigation_id: UUID):
        if investigation_id != self.investigation_id:
            return None
        return Investigation(
            id=self.investigation_id,
            incident_id=uuid4(),
            incident_request="Investigate Payment API HTTP 500 errors.",
            incident_business_status="OPEN",
            lifecycle=InvestigationLifecycle.COMPLETED,
            workflow_thread_id=f"investigation:{self.investigation_id}",
        )

    def list_investigations(self):
        return [self.get_investigation(self.investigation_id)]


def test_start_and_get_investigation_routes() -> None:
    service = FakeInvestigationService()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_investigation_service] = lambda: service
    client = TestClient(app)

    incident_id = uuid4()
    start_response = client.post(
        "/api/investigations",
        json={
            "incident_id": str(incident_id),
            "incident_request": "Investigate Payment API HTTP 500 errors.",
        },
    )

    assert start_response.status_code == 201
    assert start_response.json()["incident_id"] == str(incident_id)

    get_response = client.get(f"/api/investigations/{service.investigation_id}")

    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(service.investigation_id)

    list_response = client.get("/api/investigations")

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == str(service.investigation_id)


def test_start_investigation_returns_404_for_unknown_incident() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_investigation_service] = FakeInvestigationService
    client = TestClient(app)

    response = client.post(
        "/api/investigations",
        json={
            "incident_id": "00000000-0000-0000-0000-000000000000",
            "incident_request": "Investigate Payment API HTTP 500 errors.",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"

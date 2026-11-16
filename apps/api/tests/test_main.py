import importlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from incidentflow.application.jobs.queue import InMemoryJobQueue
from incidentflow.core.config import get_settings


def test_health_returns_ok(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    main = importlib.import_module("incidentflow.main")
    client = TestClient(main.create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_module_app_loads_ssm_secrets_before_settings(monkeypatch) -> None:
    from incidentflow.core import ssm

    def fake_loader(path: str) -> list[str]:
        assert path == "/incidentflow"
        monkeypatch.setenv("APP_NAME", "IncidentFlow from SSM")
        return ["APP_NAME"]

    main = importlib.import_module("incidentflow.main")
    monkeypatch.setenv(ssm.SSM_PATH_ENV, "/incidentflow")
    monkeypatch.setattr(ssm, "load_ssm_parameters_into_environ", fake_loader)
    get_settings()  # Cached before the secrets arrive; the module must not reuse it.

    try:
        reloaded = importlib.reload(main)
        assert reloaded.app.title == "IncidentFlow from SSM"
    finally:
        # Leave a module-level app built from the normal test settings for later tests.
        monkeypatch.delenv(ssm.SSM_PATH_ENV)
        monkeypatch.delenv("APP_NAME", raising=False)
        get_settings.cache_clear()
        importlib.reload(main)


@pytest.mark.anyio
async def test_app_lifespan_opens_checkpointer_and_shares_workflow(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    main = importlib.import_module("incidentflow.main")
    events: list[str] = []

    class FakeCheckpointerContext:
        async def __aenter__(self):
            events.append("open")
            return self

        async def __aexit__(self, *_args):
            events.append("close")

        async def setup(self) -> None:
            events.append("setup")

    monkeypatch.setattr(
        main, "build_investigation_workflow", lambda _supervisor, *, checkpointer: checkpointer
    )
    monkeypatch.setattr(main, "build_investigation_supervisor", lambda: object())

    queue = InMemoryJobQueue()
    app = main.create_app(
        checkpointer_context_factory=lambda _database_url: FakeCheckpointerContext(),
        job_queue_factory=lambda _settings: queue,
    )
    lifespan = app.router.lifespan_context(app)

    async with lifespan:
        assert app.state.investigation_workflow is not None
        assert app.state.job_queue is queue

    assert events == ["open", "close"]


def test_metrics_count_investigations_from_database(monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from incidentflow.domain.investigations.models import InvestigationCreate
    from incidentflow.infrastructure.database.base import Base
    from incidentflow.infrastructure.database.investigation_repository import (
        InvestigationRepository,
    )
    from incidentflow.infrastructure.database.models import IncidentORM

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()
    main = importlib.import_module("incidentflow.main")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        incident = IncidentORM(id=uuid4(), title="t", description="d" * 20, priority="HIGH")
        session.add(incident)
        session.commit()
        InvestigationRepository(session).create_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request="Investigate it.",
                incident_business_status="OPEN",
            )
        )
    monkeypatch.setattr(main, "SessionLocal", session_factory)

    client = TestClient(main.create_app())
    body = client.get("/operations/metrics").json()

    assert body["investigations_by_lifecycle"] == {"PENDING": 1}
    assert "requests_by_status" in body

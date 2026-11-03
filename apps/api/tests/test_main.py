import importlib

import pytest
from fastapi.testclient import TestClient

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

    def fake_recovery() -> int:
        events.append("recover")
        return 0

    app = main.create_app(
        checkpointer_context_factory=lambda _database_url: FakeCheckpointerContext(),
        recover_interrupted_investigations=fake_recovery,
    )
    lifespan = app.router.lifespan_context(app)

    async with lifespan:
        assert app.state.investigation_workflow is not None

    # Interrupted runs are cleaned up before the workflow accepts new investigations.
    assert events == ["recover", "open", "setup", "close"]

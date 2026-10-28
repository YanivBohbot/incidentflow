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


def test_app_lifespan_opens_checkpointer_and_shares_workflow(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()

    main = importlib.import_module("incidentflow.main")
    events: list[str] = []

    class FakeCheckpointerContext:
        def __enter__(self):
            events.append("open")
            return self

        def __exit__(self, *_args):
            events.append("close")

        def setup(self) -> None:
            events.append("setup")

    monkeypatch.setattr(main, "build_investigation_workflow", lambda *, checkpointer: checkpointer)
    monkeypatch.setattr(main, "build_jira_action_workflow", lambda *, checkpointer: checkpointer)

    app = main.create_app(checkpointer_context_factory=lambda _database_url: FakeCheckpointerContext())
    lifespan = app.router.lifespan_context(app)

    with pytest.raises(StopIteration):
        lifespan.__aenter__().send(None)
    assert app.state.investigation_workflow is not None
    assert app.state.jira_action_workflow is not None

    with pytest.raises(StopIteration):
        lifespan.__aexit__(None, None, None).send(None)

    assert events == ["open", "setup", "close"]

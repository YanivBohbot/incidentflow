import importlib

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

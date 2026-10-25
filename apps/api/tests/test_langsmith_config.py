from incidentflow.core.config import get_settings


def test_langsmith_tracing_configuration_uses_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_PROJECT", "incidentflow-test")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-langsmith-key")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.langsmith_project == "incidentflow-test"
    assert settings.langsmith_tracing is True

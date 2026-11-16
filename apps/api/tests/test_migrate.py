import pytest

from incidentflow import migrate
from incidentflow.core.config import get_settings


def test_migrate_runs_alembic_then_checkpointer_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv(
        "LANGGRAPH_CHECKPOINT_DATABASE_URL",
        "postgresql://incidentflow:password@localhost:5432/incidentflow_checkpoints",
    )
    config_path = tmp_path / "alembic.ini"
    monkeypatch.setenv("ALEMBIC_CONFIG", str(config_path))
    get_settings.cache_clear()
    events: list[object] = []

    def fake_upgrade(config, revision: str) -> None:
        events.append(("upgrade", config.config_file_name, revision))

    class FakeCheckpointerContext:
        async def __aenter__(self):
            events.append("open")
            return self

        async def __aexit__(self, *_args):
            events.append("close")

        async def setup(self) -> None:
            events.append("setup")

    def fake_checkpointer(database_url: str) -> FakeCheckpointerContext:
        events.append(("checkpointer", database_url))
        return FakeCheckpointerContext()

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(migrate, "open_postgres_checkpointer", fake_checkpointer)

    try:
        migrate.run_migrations()
    finally:
        get_settings.cache_clear()

    assert events == [
        ("upgrade", str(config_path), "head"),
        (
            "checkpointer",
            "postgresql://incidentflow:password@localhost:5432/incidentflow_checkpoints",
        ),
        "open",
        "setup",
        "close",
    ]

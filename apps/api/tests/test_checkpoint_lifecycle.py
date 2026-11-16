import pytest
from langgraph.checkpoint.memory import InMemorySaver

from incidentflow.agent.orchestration.checkpoints import postgres
from incidentflow.agent.orchestration.checkpoints.postgres import (
    normalize_checkpoint_database_url,
)
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)


def test_database_url_is_normalized_for_postgres_saver() -> None:
    assert (
        normalize_checkpoint_database_url("postgresql+psycopg://user:password@db:5432/incidentflow")
        == "postgresql://user:password@db:5432/incidentflow"
    )


def test_workflow_compiles_with_injected_checkpointer() -> None:
    workflow = build_investigation_workflow(lambda _state: {}, checkpointer=InMemorySaver())

    assert workflow is not None


def test_open_postgres_checkpointer_uses_normalized_database_url(monkeypatch) -> None:
    captured: list[str] = []

    def create_fake_saver(database_url: str) -> object:
        captured.append(database_url)
        return object()

    monkeypatch.setattr(postgres, "_open_postgres_saver", create_fake_saver)

    checkpointer_context = postgres.open_postgres_checkpointer(
        "postgresql+psycopg://user:password@db:5432/incidentflow"
    )

    assert checkpointer_context is not None
    assert captured == ["postgresql://user:password@db:5432/incidentflow"]


@pytest.mark.anyio
async def test_postgres_checkpointer_uses_checked_pool_without_idle_connections(
    monkeypatch,
) -> None:
    import psycopg_pool
    from langgraph.checkpoint.postgres import aio as saver_module
    from psycopg.rows import dict_row

    events: list[object] = []

    class FakePool:
        check_connection = psycopg_pool.AsyncConnectionPool.check_connection

        def __init__(self, conninfo: str, **options: object) -> None:
            events.append(("pool", conninfo, options))

        async def open(self) -> None:
            events.append("open")

        async def close(self) -> None:
            events.append("close")

    class FakeSaver:
        def __init__(self, *, conn: object) -> None:
            self.conn = conn

    monkeypatch.setattr(psycopg_pool, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(saver_module, "AsyncPostgresSaver", FakeSaver)

    async with postgres.open_postgres_checkpointer(
        "postgresql+psycopg://user:password@db:5432/incidentflow"
    ) as saver:
        assert isinstance(saver, FakeSaver)
        assert isinstance(saver.conn, FakePool)
        events.append("used")

    (_, conninfo, options), *lifecycle = events
    assert conninfo == "postgresql://user:password@db:5432/incidentflow"
    assert options == {
        "min_size": 0,
        "max_size": postgres.CHECKPOINT_POOL_MAX_SIZE,
        "max_idle": 60.0,
        "check": psycopg_pool.AsyncConnectionPool.check_connection,
        "kwargs": {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        "open": False,
    }
    assert lifecycle == ["open", "used", "close"]

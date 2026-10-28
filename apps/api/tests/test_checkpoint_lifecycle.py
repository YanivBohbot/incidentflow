from langgraph.checkpoint.memory import InMemorySaver

from incidentflow.agent.orchestration import checkpoints
from incidentflow.agent.orchestration.checkpoints import normalize_checkpoint_database_url
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)


def test_database_url_is_normalized_for_postgres_saver() -> None:
    assert (
        normalize_checkpoint_database_url("postgresql+psycopg://user:password@db:5432/incidentflow")
        == "postgresql://user:password@db:5432/incidentflow"
    )


def test_workflow_compiles_with_injected_checkpointer() -> None:
    workflow = build_investigation_workflow(checkpointer=InMemorySaver())

    assert workflow is not None


def test_open_postgres_checkpointer_uses_normalized_database_url(monkeypatch) -> None:
    captured: list[str] = []

    def create_fake_saver(database_url: str) -> object:
        captured.append(database_url)
        return object()

    monkeypatch.setattr(checkpoints, "_open_postgres_saver", create_fake_saver)

    checkpointer_context = checkpoints.open_postgres_checkpointer(
        "postgresql+psycopg://user:password@db:5432/incidentflow"
    )

    assert checkpointer_context is not None
    assert captured == ["postgresql://user:password@db:5432/incidentflow"]

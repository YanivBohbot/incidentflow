import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow import lambda_handlers
from incidentflow.application.jobs.processor import JobOutcome
from incidentflow.application.jobs.queue import InMemoryJobQueue, ReceivedJob
from incidentflow.core import ssm
from incidentflow.core.config import Settings, get_settings
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import InvestigationCreate, utc_now
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM

KeepAlive = Callable[[], Awaitable[None]]


class FakeProcessor:
    def __init__(self, behaviour: Callable[[UUID, KeepAlive], Awaitable[JobOutcome]]) -> None:
        self.behaviour = behaviour
        self.processed: list[UUID] = []

    async def process(self, investigation_id: UUID, *, keep_alive: KeepAlive) -> JobOutcome:
        self.processed.append(investigation_id)
        return await self.behaviour(investigation_id, keep_alive)


async def _complete(_investigation_id: UUID, keep_alive: KeepAlive) -> JobOutcome:
    await keep_alive()
    return JobOutcome.COMPLETED


@pytest.fixture(autouse=True)
def _fresh_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(ssm.SSM_PATH_ENV, raising=False)
    lambda_handlers.reset_runtime()
    yield
    lambda_handlers.reset_runtime()


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def wire_worker(
    monkeypatch: pytest.MonkeyPatch, queue: InMemoryJobQueue
) -> Callable[[FakeProcessor], dict[str, int]]:
    """Replace the worker's builders with an InMemorySaver, a fake processor and queue."""

    def wire(processor: FakeProcessor) -> dict[str, int]:
        calls = {"checkpointer": 0, "workflow": 0, "processor": 0}

        def checkpointer_context(_url: str) -> Any:
            calls["checkpointer"] += 1
            return contextlib.nullcontext(InMemorySaver())

        def workflow_builder(checkpointer: Any) -> Any:
            calls["workflow"] += 1
            assert isinstance(checkpointer, InMemorySaver)
            return object()

        def processor_builder(_settings: Settings, _session_factory: Any, _workflow: Any) -> Any:
            calls["processor"] += 1
            return processor

        monkeypatch.setattr(lambda_handlers, "checkpointer_context_factory", checkpointer_context)
        monkeypatch.setattr(lambda_handlers, "workflow_builder", workflow_builder)
        monkeypatch.setattr(lambda_handlers, "processor_builder", processor_builder)
        monkeypatch.setattr(lambda_handlers, "session_factory_provider", lambda: sessionmaker())
        monkeypatch.setattr(lambda_handlers, "job_queue_factory", lambda _settings: queue)
        return calls

    return wire


def _record(message_id: str, body: str, receipt: str | None = None) -> dict[str, str]:
    return {"messageId": message_id, "receiptHandle": receipt or f"rh-{message_id}", "body": body}


def _job_body(investigation_id: UUID) -> str:
    return json.dumps({"investigation_id": str(investigation_id)})


def test_worker_handler_reports_only_crashed_records(wire_worker) -> None:
    crashing, completed, dropped = uuid4(), uuid4(), uuid4()

    async def behaviour(investigation_id: UUID, _keep_alive: KeepAlive) -> JobOutcome:
        if investigation_id == crashing:
            raise RuntimeError("boom")
        return JobOutcome.COMPLETED if investigation_id == completed else JobOutcome.DROPPED

    processor = FakeProcessor(behaviour)
    wire_worker(processor)
    event = {
        "Records": [
            _record("m-crash", _job_body(crashing)),
            _record("m-done", _job_body(completed)),
            _record("m-drop", _job_body(dropped)),
        ]
    }

    result = lambda_handlers.worker_handler(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-crash"}]}
    assert processor.processed == [crashing, completed, dropped]


@pytest.mark.parametrize(
    "body", ["not json", "{}", json.dumps({"investigation_id": "nope"}), "[]", "null"]
)
def test_worker_handler_acknowledges_malformed_body(wire_worker, body: str) -> None:
    processor = FakeProcessor(_complete)
    wire_worker(processor)

    result = lambda_handlers.worker_handler({"Records": [_record("m-bad", body)]}, None)

    assert result == {"batchItemFailures": []}
    assert processor.processed == []


def test_keep_alive_extends_with_receipt_handle(
    wire_worker, queue: InMemoryJobQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JOB_LEASE_SECONDS", "321")
    investigation_id = uuid4()
    wire_worker(FakeProcessor(_complete))

    result = lambda_handlers.worker_handler(
        {"Records": [_record("m-1", _job_body(investigation_id), receipt="receipt-xyz")]}, None
    )

    assert result == {"batchItemFailures": []}
    assert queue.extended == [(ReceivedJob(investigation_id, "receipt-xyz"), 321)]


def test_keep_alive_swallows_extend_errors(
    wire_worker, queue: InMemoryJobQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_extend(_job: ReceivedJob, *, visibility_seconds: int) -> None:
        raise RuntimeError("sqs down")

    monkeypatch.setattr(queue, "extend", failing_extend)
    wire_worker(FakeProcessor(_complete))

    result = lambda_handlers.worker_handler({"Records": [_record("m-1", _job_body(uuid4()))]}, None)

    assert result == {"batchItemFailures": []}


def test_warm_invocation_reuses_loop_and_workflow(wire_worker, queue: InMemoryJobQueue) -> None:
    loops: list[asyncio.AbstractEventLoop] = []

    async def behaviour(_investigation_id: UUID, keep_alive: KeepAlive) -> JobOutcome:
        loops.append(asyncio.get_running_loop())
        await keep_alive()
        return JobOutcome.COMPLETED

    calls = wire_worker(FakeProcessor(behaviour))

    first = lambda_handlers.worker_handler({"Records": [_record("m-1", _job_body(uuid4()))]}, None)
    second = lambda_handlers.worker_handler({"Records": [_record("m-2", _job_body(uuid4()))]}, None)

    assert first == second == {"batchItemFailures": []}
    assert calls == {"checkpointer": 1, "workflow": 1, "processor": 1}
    assert len(loops) == 2 and loops[0] is loops[1]
    assert len(queue.extended) == 2


def test_worker_setup_failure_is_retried_on_next_invocation(
    wire_worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = wire_worker(FakeProcessor(_complete))
    real_builder = lambda_handlers.workflow_builder
    attempts = {"n": 0}

    def flaky_builder(checkpointer: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("cold start failed")
        return real_builder(checkpointer)

    monkeypatch.setattr(lambda_handlers, "workflow_builder", flaky_builder)
    event = {"Records": [_record("m-1", _job_body(uuid4()))]}

    with pytest.raises(RuntimeError, match="cold start failed"):
        lambda_handlers.worker_handler(event, None)
    assert lambda_handlers.worker_handler(event, None) == {"batchItemFailures": []}
    assert calls["checkpointer"] == 2


def test_worker_refuses_interactive_jira_oauth_in_aws(
    wire_worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ssm.SSM_PATH_ENV, "/incidentflow")
    monkeypatch.setattr(ssm, "load_ssm_parameters_into_environ", lambda _path: [])
    monkeypatch.setenv("JIRA_MCP_ENABLED", "true")
    # Empty values, not delenv: a developer's apps/api/.env may configure a local store.
    monkeypatch.setenv("MCP_OAUTH_TOKEN_STORE", "disk")
    monkeypatch.setenv("MCP_OAUTH_TOKEN_STORE_DIR", "")
    monkeypatch.setenv("MCP_OAUTH_STORAGE_ENCRYPTION_KEY", "")
    calls = wire_worker(FakeProcessor(_complete))

    with pytest.raises(RuntimeError, match="MCP_OAUTH_TOKEN_STORE"):
        lambda_handlers.worker_handler({"Records": [_record("m-1", _job_body(uuid4()))]}, None)
    assert calls["checkpointer"] == 0


@pytest.fixture
def sqlite_session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_sweeper_handler_returns_resent_count(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session_factory: sessionmaker[Session],
    queue: InMemoryJobQueue,
) -> None:
    with sqlite_session_factory() as session:
        incident = IncidentORM(
            id=uuid4(), title="API", description="500s.", priority=IncidentPriority.HIGH
        )
        session.add(incident)
        session.commit()
        stale = (
            InvestigationRepository(session)
            .create_investigation(
                InvestigationCreate(
                    incident_id=incident.id,
                    incident_request="Investigate.",
                    incident_business_status="OPEN",
                )
            )
            .id
        )
        session.execute(
            update(InvestigationORM)
            .where(InvestigationORM.id == stale)
            .values(updated_at=utc_now() - timedelta(seconds=600))
        )
        session.commit()
    monkeypatch.setattr(lambda_handlers, "session_factory_provider", lambda: sqlite_session_factory)
    monkeypatch.setattr(lambda_handlers, "job_queue_factory", lambda _settings: queue)

    result = lambda_handlers.sweeper_handler({}, None)

    assert result == {"resent": 1}
    assert queue.sent == [stale]


def test_migrate_handler_runs_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[str] = []
    monkeypatch.setattr(lambda_handlers, "run_migrations", lambda: runs.append("migrated"))

    assert lambda_handlers.migrate_handler({}, None) == {"status": "migrated"}
    assert runs == ["migrated"]


def test_handlers_load_ssm_when_path_set(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded_paths: list[str] = []
    seen_lease_seconds: list[int] = []

    def fake_loader(path: str) -> list[str]:
        loaded_paths.append(path)
        monkeypatch.setenv("JOB_LEASE_SECONDS", "77")
        return ["JOB_LEASE_SECONDS"]

    # A settings object cached before the secrets arrive must not be reused.
    get_settings()
    monkeypatch.setenv(ssm.SSM_PATH_ENV, "/incidentflow")
    monkeypatch.setattr(ssm, "load_ssm_parameters_into_environ", fake_loader)
    monkeypatch.setattr(
        lambda_handlers,
        "run_migrations",
        lambda: seen_lease_seconds.append(get_settings().job_lease_seconds),
    )

    lambda_handlers.migrate_handler({}, None)
    lambda_handlers.migrate_handler({}, None)

    assert loaded_paths == ["/incidentflow"]
    assert seen_lease_seconds == [77, 77]


def test_handlers_skip_ssm_without_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_loader(_path: str) -> list[str]:
        raise AssertionError("SSM must not be read without INCIDENTFLOW_SSM_PATH")

    monkeypatch.setattr(ssm, "load_ssm_parameters_into_environ", unexpected_loader)
    monkeypatch.setattr(lambda_handlers, "run_migrations", lambda: None)

    assert lambda_handlers.migrate_handler({}, None) == {"status": "migrated"}

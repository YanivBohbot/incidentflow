import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.application.jobs.processor import JobOutcome
from incidentflow.application.jobs.queue import InMemoryJobQueue
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import InvestigationCreate, utc_now
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM
from incidentflow.worker import run_worker, sweep_stale_investigations

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeProcessor:
    def __init__(
        self,
        *,
        gate: asyncio.Event | None = None,
        crash_on: set[UUID] | None = None,
        use_keep_alive: bool = False,
    ) -> None:
        self.gate = gate
        self.crash_on = crash_on or set()
        self.use_keep_alive = use_keep_alive
        self.started: list[UUID] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def process(
        self,
        investigation_id: UUID,
        *,
        keep_alive: Callable[[], Awaitable[None]] | None = None,
    ) -> JobOutcome:
        self.started.append(investigation_id)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.use_keep_alive and keep_alive is not None:
                await keep_alive()
            if self.gate is not None:
                await self.gate.wait()
            else:
                await asyncio.sleep(0.01)
            if investigation_id in self.crash_on:
                raise RuntimeError("boom")
            return JobOutcome.COMPLETED
        finally:
            self.in_flight -= 1


async def _run_until(
    queue: InMemoryJobQueue,
    processor: FakeProcessor,
    done: Callable[[], bool],
    *,
    concurrency: int = 2,
) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(
            queue,
            processor,  # type: ignore[arg-type]
            concurrency=concurrency,
            lease_seconds=300,
            stop=stop,
            poll_wait_seconds=0,
        )
    )
    for _ in range(500):
        if done():
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_worker_processes_and_acks_each_job() -> None:
    queue = InMemoryJobQueue()
    ids = [uuid4() for _ in range(3)]
    for investigation_id in ids:
        queue.send(investigation_id)
    processor = FakeProcessor(use_keep_alive=True)

    await _run_until(queue, processor, lambda: len(queue.acked) == 3)

    assert {job.investigation_id for job in queue.acked} == set(ids)
    assert len(queue.extended) == 3
    assert all(seconds == 300 for _, seconds in queue.extended)


async def test_worker_respects_concurrency() -> None:
    queue = InMemoryJobQueue()
    for _ in range(5):
        queue.send(uuid4())
    processor = FakeProcessor()

    await _run_until(queue, processor, lambda: len(queue.acked) == 5, concurrency=2)

    assert processor.max_in_flight == 2
    assert len(queue.acked) == 5


async def test_worker_does_not_ack_when_processor_crashes() -> None:
    queue = InMemoryJobQueue()
    bad, good = uuid4(), uuid4()
    queue.send(bad)
    queue.send(good)
    processor = FakeProcessor(crash_on={bad})

    await _run_until(queue, processor, lambda: len(queue.acked) == 1)
    await asyncio.sleep(0.05)

    assert [job.investigation_id for job in queue.acked] == [good]


async def test_worker_stops_after_in_flight_jobs() -> None:
    queue = InMemoryJobQueue()
    queue.send(uuid4())
    gate = asyncio.Event()
    processor = FakeProcessor(gate=gate)
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(
            queue,
            processor,  # type: ignore[arg-type]
            concurrency=2,
            lease_seconds=300,
            stop=stop,
            poll_wait_seconds=0,
        )
    )
    for _ in range(500):
        if processor.started:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.sleep(0.05)

    assert not task.done()
    assert queue.acked == []

    gate.set()
    await asyncio.wait_for(task, timeout=5)

    assert len(queue.acked) == 1


async def test_worker_runs_the_sweeper_and_survives_its_failure() -> None:
    queue = InMemoryJobQueue()
    calls: list[int] = []

    def sweep() -> int:
        calls.append(1)
        raise RuntimeError("db down")

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(
            queue,
            FakeProcessor(),  # type: ignore[arg-type]
            concurrency=1,
            lease_seconds=300,
            stop=stop,
            sweep=sweep,
            sweep_interval_seconds=0.01,
            poll_wait_seconds=0,
        )
    )
    for _ in range(500):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert len(calls) >= 2


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)


def test_sweeper_resends_stale_rows(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        incident = IncidentORM(
            id=uuid4(), title="API", description="500s.", priority=IncidentPriority.HIGH
        )
        session.add(incident)
        session.commit()
        repo = InvestigationRepository(session)

        def create() -> UUID:
            return repo.create_investigation(
                InvestigationCreate(
                    incident_id=incident.id,
                    incident_request="Investigate.",
                    incident_business_status="OPEN",
                )
            ).id

        fresh, old_pending, expired = create(), create(), create()
        now = utc_now()
        session.execute(
            update(InvestigationORM)
            .where(InvestigationORM.id == old_pending)
            .values(updated_at=now - timedelta(seconds=121))
        )
        session.commit()
        repo.claim(expired, lease_seconds=300, now=now - timedelta(seconds=400))
    queue = InMemoryJobQueue()

    resent = sweep_stale_investigations(session_factory, queue)

    assert resent == 2
    assert set(queue.sent) == {old_pending, expired}
    assert fresh not in queue.sent

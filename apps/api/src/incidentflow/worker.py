"""Long-running worker: drains the investigation queue and re-sends stale rows.

All per-job logic lives in ``InvestigationJobProcessor``; this module is only the driver, so
an AWS Lambda handler can call the same processor later.
"""

import asyncio
import contextlib
import logging
import signal
import sys
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from incidentflow.agent.orchestration.checkpoints.postgres import open_postgres_checkpointer
from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.application.jobs.processor import InvestigationJobProcessor
from incidentflow.application.jobs.queue import JobQueue, ReceivedJob
from incidentflow.core.config import Settings, get_settings
from incidentflow.infrastructure.database.investigation_repository import InvestigationRepository
from incidentflow.infrastructure.database.session import get_session_factory
from incidentflow.infrastructure.queue.sqs import build_job_queue

logger = logging.getLogger(__name__)

SQS_MAX_MESSAGES = 10
SQS_MAX_WAIT_SECONDS = 20
IDLE_PAUSE_SECONDS = 0.05
SLOT_WAIT_SECONDS = 0.1
STALE_PENDING_SECONDS = 120


def sweep_stale_investigations(
    session_factory: Callable[[], Session],
    queue: JobQueue,
    *,
    pending_older_than_seconds: int = STALE_PENDING_SECONDS,
) -> int:
    """Re-send stale PENDING rows and RUNNING rows with expired leases; return how many."""
    with session_factory() as session:
        ids = InvestigationRepository(session).stale_investigation_ids(
            pending_older_than_seconds=pending_older_than_seconds
        )
    for investigation_id in ids:
        queue.send(investigation_id)
    return len(ids)


async def run_worker(
    queue: JobQueue,
    processor: InvestigationJobProcessor,
    *,
    concurrency: int,
    lease_seconds: int,
    stop: asyncio.Event,
    sweep: Callable[[], int] | None = None,
    sweep_interval_seconds: float = 60,
    poll_wait_seconds: int = 10,
    receive_error_backoff_seconds: float = 5,
) -> None:
    """Run up to ``concurrency`` jobs at once until ``stop`` is set, then drain in-flight jobs."""
    in_flight: set[asyncio.Task[None]] = set()
    next_sweep_at = time.monotonic()

    async def handle(job: ReceivedJob) -> None:
        async def keep_alive() -> None:
            try:
                await asyncio.to_thread(queue.extend, job, visibility_seconds=lease_seconds)
            except Exception:
                logger.exception("Could not extend visibility for %s.", job.investigation_id)

        try:
            outcome = await processor.process(job.investigation_id, keep_alive=keep_alive)
        except Exception:
            # Not acked: the queue redelivers the message, and the dead-letter queue catches it.
            logger.exception("Investigation job %s crashed.", job.investigation_id)
            return
        logger.info("Investigation job %s finished: %s.", job.investigation_id, outcome.value)
        try:
            await asyncio.to_thread(queue.ack, job)
        except Exception:
            logger.exception("Could not acknowledge job %s.", job.investigation_id)

    def run_sweep() -> int:
        assert sweep is not None
        return sweep()

    try:
        while not stop.is_set():
            if sweep is not None and time.monotonic() >= next_sweep_at:
                next_sweep_at = time.monotonic() + sweep_interval_seconds
                try:
                    resent = await asyncio.to_thread(run_sweep)
                    if resent:
                        logger.info("Sweeper re-sent %d stale investigation(s).", resent)
                except Exception:
                    logger.exception("Sweeper failed.")

            free = concurrency - len(in_flight)
            if free <= 0:
                await asyncio.wait(
                    in_flight, timeout=SLOT_WAIT_SECONDS, return_when=asyncio.FIRST_COMPLETED
                )
                continue

            try:
                jobs = await asyncio.to_thread(
                    queue.receive,
                    max_messages=min(free, SQS_MAX_MESSAGES),
                    wait_seconds=min(poll_wait_seconds, SQS_MAX_WAIT_SECONDS),
                )
            except Exception:
                logger.exception("Receiving from the job queue failed.")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=receive_error_backoff_seconds)
                continue
            if not jobs:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=IDLE_PAUSE_SECONDS)
                continue
            for job in jobs:
                task = asyncio.create_task(handle(job))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
    finally:
        # Graceful stop drains in-flight jobs. If the process is killed mid-drain, those jobs are
        # abandoned mid-run and messages fetched by a cancelled receive stay invisible until their
        # visibility timeout; recovery relies on lease expiry, the sweeper, and SQS redelivery.
        if in_flight:
            await asyncio.gather(*list(in_flight), return_exceptions=True)


def build_processor(
    settings: Settings, session_factory: Callable[[], Session], workflow: Any
) -> InvestigationJobProcessor:
    return InvestigationJobProcessor(
        session_factory,
        workflow,
        lease_seconds=settings.job_lease_seconds,
        max_attempts=settings.job_max_attempts,
        timeout_seconds=settings.job_timeout_seconds,
    )


async def main() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    queue = build_job_queue(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: KeyboardInterrupt is handled by the caller.
            pass

    async with open_postgres_checkpointer(settings.checkpoint_database_url) as checkpointer:
        await checkpointer.setup()
        workflow: Any = build_investigation_workflow(
            build_investigation_supervisor(), checkpointer=checkpointer
        )
        processor = build_processor(settings, session_factory, workflow)
        logger.info("Worker started with concurrency %d.", settings.worker_concurrency)
        main_task = asyncio.create_task(
            run_worker(
                queue,
                processor,
                concurrency=settings.worker_concurrency,
                lease_seconds=settings.job_lease_seconds,
                stop=stop,
                sweep=lambda: sweep_stale_investigations(session_factory, queue),
            )
        )
        try:
            await main_task
        except asyncio.CancelledError:
            stop.set()
            await main_task
            raise
    logger.info("Worker stopped.")


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    # psycopg's async driver cannot run on Windows' default ProactorEventLoop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(), loop_factory=loop_factory)


if __name__ == "__main__":
    run()

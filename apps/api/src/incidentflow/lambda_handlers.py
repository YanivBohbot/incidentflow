"""AWS Lambda entry points: the SQS worker, the stale-row sweeper, and one-shot migrations.

They reuse the local worker's job code. One runtime lives per Lambda execution environment: a
persistent event loop and, after the first worker invocation, the checkpointer, workflow and
processor. Warm invocations reuse them; nothing is torn down, since Lambda freezes or discards
the environment itself. The builders below are module attributes so tests can replace them.
"""

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from incidentflow.agent.mcp_clients.oauth_store import (
    build_oauth_token_storage,
    close_oauth_token_storage,
)
from incidentflow.agent.orchestration.checkpoints.postgres import open_postgres_checkpointer
from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.application.jobs.processor import InvestigationJobProcessor
from incidentflow.application.jobs.queue import JobQueue, ReceivedJob
from incidentflow.core.config import Settings, get_settings
from incidentflow.core.ssm import SSM_PATH_ENV, load_ssm_secrets_if_configured
from incidentflow.infrastructure.database.session import get_session_factory
from incidentflow.infrastructure.queue.sqs import build_job_queue
from incidentflow.migrate import run_migrations
from incidentflow.worker import build_processor, sweep_stale_investigations

logger = logging.getLogger(__name__)

JIRA_TOKEN_STORE_REQUIRED_MESSAGE = (
    "JIRA_MCP_ENABLED is true but no Jira OAuth token store is configured. On AWS set "
    "MCP_OAUTH_TOKEN_STORE=dynamodb, MCP_OAUTH_DYNAMODB_TABLE and "
    "MCP_OAUTH_STORAGE_ENCRYPTION_KEY; without a store the Jira client would wait for a browser."
)


def workflow_builder(checkpointer: Any) -> Any:
    return build_investigation_workflow(build_investigation_supervisor(), checkpointer=checkpointer)


checkpointer_context_factory: Callable[[str], AbstractAsyncContextManager[Any]] = (
    open_postgres_checkpointer
)
processor_builder: Callable[..., InvestigationJobProcessor] = build_processor
session_factory_provider: Callable[[], Callable[[], Session]] = get_session_factory
job_queue_factory: Callable[[Settings], JobQueue] = build_job_queue


@dataclass
class _WorkerRuntime:
    settings: Settings
    queue: JobQueue
    processor: InvestigationJobProcessor
    resources: AsyncExitStack


_loop: asyncio.AbstractEventLoop | None = None
_worker_runtime: _WorkerRuntime | None = None
_environment_loaded = False


def _load_environment() -> None:
    """Read SSM secrets once per execution environment, before any settings are built."""
    global _environment_loaded
    if _environment_loaded:
        return
    names = load_ssm_secrets_if_configured()
    if names:
        logger.info("Loaded %d parameter(s) from SSM.", len(names))
    _environment_loaded = True


def _event_loop() -> asyncio.AbstractEventLoop:
    """Return the environment's persistent loop; ``asyncio.run`` would close it after each call."""
    global _loop
    if _loop is None or _loop.is_closed():
        # psycopg's async driver cannot run on Windows' default ProactorEventLoop (local tests).
        _loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    return _loop


async def _require_noninteractive_jira(settings: Settings) -> None:
    """On AWS, refuse to start when Jira would fall back to the interactive browser flow."""
    if not os.environ.get(SSM_PATH_ENV) or not settings.jira_mcp_enabled:
        return
    storage = build_oauth_token_storage(settings)
    if storage is None:
        raise RuntimeError(JIRA_TOKEN_STORE_REQUIRED_MESSAGE)
    await close_oauth_token_storage(storage)


async def _open_worker_runtime() -> _WorkerRuntime:
    settings = get_settings()
    await _require_noninteractive_jira(settings)
    resources = AsyncExitStack()
    try:
        checkpointer = await resources.enter_async_context(
            checkpointer_context_factory(settings.checkpoint_database_url)
        )
        workflow = workflow_builder(checkpointer)
        processor = processor_builder(settings, session_factory_provider(), workflow)
        queue = job_queue_factory(settings)
    except BaseException:
        await resources.aclose()
        raise
    return _WorkerRuntime(settings, queue, processor, resources)


async def _process_record(runtime: _WorkerRuntime, record: dict[str, Any]) -> bool:
    """Run one SQS record; return False only when SQS should redeliver it."""
    message_id = record.get("messageId")
    try:
        investigation_id = UUID(json.loads(record["body"])["investigation_id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        # Redelivering a malformed message can never succeed; let Lambda delete it.
        logger.warning("Dropping malformed job queue message %s.", message_id)
        return True
    job = ReceivedJob(investigation_id=investigation_id, receipt=record["receiptHandle"])

    async def keep_alive() -> None:
        try:
            await asyncio.to_thread(
                runtime.queue.extend, job, visibility_seconds=runtime.settings.job_lease_seconds
            )
        except Exception:
            logger.exception("Could not extend visibility for %s.", investigation_id)

    try:
        outcome = await runtime.processor.process(investigation_id, keep_alive=keep_alive)
    except Exception:
        # Reported as a batch item failure: SQS redelivers and the dead-letter queue catches it.
        logger.exception("Investigation job %s crashed.", investigation_id)
        return False
    logger.info("Investigation job %s finished: %s.", investigation_id, outcome.value)
    return True


async def _process_records(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    global _worker_runtime
    if _worker_runtime is None:
        _worker_runtime = await _open_worker_runtime()
    failures: list[dict[str, str]] = []
    for record in records:
        if not await _process_record(_worker_runtime, record):
            failures.append({"itemIdentifier": record["messageId"]})
    return failures


def worker_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS event source handler using ``ReportBatchItemFailures``.

    Successful records are deleted by Lambda, so the handler never acknowledges them itself.
    """
    _load_environment()
    failures = _event_loop().run_until_complete(_process_records(event.get("Records", [])))
    return {"batchItemFailures": failures}


def sweeper_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Scheduled handler: re-send stale PENDING rows and RUNNING rows with expired leases."""
    _load_environment()
    queue = job_queue_factory(get_settings())
    resent = sweep_stale_investigations(session_factory_provider(), queue)
    if resent:
        logger.info("Sweeper re-sent %d stale investigation(s).", resent)
    return {"resent": resent}


def migrate_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Deploy-time handler: Alembic migrations, then the LangGraph checkpoint tables."""
    _load_environment()
    run_migrations()
    return {"status": "migrated"}


def reset_runtime() -> None:
    """Close the cached worker runtime and loop and forget loaded SSM state (tests only)."""
    global _loop, _worker_runtime, _environment_loaded
    if _loop is not None and not _loop.is_closed():
        if _worker_runtime is not None:
            _loop.run_until_complete(_worker_runtime.resources.aclose())
        _loop.run_until_complete(_loop.shutdown_default_executor())
        _loop.close()
    _loop = None
    _worker_runtime = None
    _environment_loaded = False

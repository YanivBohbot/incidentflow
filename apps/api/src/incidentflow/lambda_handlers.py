"""AWS Lambda entry points: the SQS worker, the stale-row sweeper, the alarm ingester, and
one-shot migrations.

``ingest_handler`` turns CloudWatch alarm state changes (via EventBridge) into incidents.

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
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import boto3
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
from incidentflow.application.services.incident_ingestion_service import (
    AlarmTagReader,
    CloudWatchAlarmTagReader,
    IncidentIngestionService,
)
from incidentflow.core.config import Settings, get_settings
from incidentflow.core.ssm import SSM_PATH_ENV, load_ssm_secrets_if_configured
from incidentflow.demo.simulator import DemoSimulator
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.session import get_session_factory
from incidentflow.infrastructure.queue.sqs import build_job_queue
from incidentflow.migrate import run_migrations
from incidentflow.worker import build_processor, sweep_stale_investigations

logger = logging.getLogger(__name__)


def configure_lambda_logging() -> None:
    """Show INFO logs in Lambda, whose root logger otherwise drops them.

    Only inside Lambda, and only when the function has no log level of its own configured.
    """
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("AWS_LAMBDA_LOG_LEVEL"):
        return
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    elif root.level > logging.INFO:
        root.setLevel(logging.INFO)


configure_lambda_logging()

JIRA_TOKEN_STORE_REQUIRED_MESSAGE = (
    "JIRA_MCP_ENABLED is true but no Jira OAuth token store is configured. On AWS set "
    "MCP_OAUTH_TOKEN_STORE=dynamodb, MCP_OAUTH_DYNAMODB_TABLE and "
    "MCP_OAUTH_STORAGE_ENCRYPTION_KEY; without a store the Jira client would wait for a browser."
)


def workflow_builder(checkpointer: Any) -> Any:
    """Build the investigation workflow for a Lambda invocation."""
    return build_investigation_workflow(build_investigation_supervisor(), checkpointer=checkpointer)


checkpointer_context_factory: Callable[[str], AbstractAsyncContextManager[Any]] = (
    open_postgres_checkpointer
)
processor_builder: Callable[..., InvestigationJobProcessor] = build_processor
session_factory_provider: Callable[[], Callable[[], Session]] = get_session_factory
job_queue_factory: Callable[[Settings], JobQueue] = build_job_queue


def _build_alarm_tag_reader() -> AlarmTagReader:
    return CloudWatchAlarmTagReader(boto3.client("cloudwatch"))


alarm_tag_reader_factory: Callable[[], AlarmTagReader] = _build_alarm_tag_reader


def _build_demo_simulator(settings: Settings) -> DemoSimulator:
    return DemoSimulator(
        boto3.client("logs"),
        boto3.client("cloudwatch"),
        boto3.client("sts"),
        interval_seconds=settings.demo_interval_seconds,
    )


demo_simulator_factory: Callable[[Settings], DemoSimulator] = _build_demo_simulator


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


def _parse_record(record: Any) -> tuple[str, ReceivedJob] | None:
    """Return the record's message id and job, or None when it can never be processed."""
    try:
        message_id = record["messageId"]
        receipt = record["receiptHandle"]
        investigation_id = UUID(json.loads(record["body"])["investigation_id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if not isinstance(message_id, str) or not isinstance(receipt, str):
        return None
    return message_id, ReceivedJob(investigation_id=investigation_id, receipt=receipt)


async def _process_job(runtime: _WorkerRuntime, job: ReceivedJob) -> bool:
    """Run one job; return False only when SQS should redeliver it."""
    investigation_id = job.investigation_id

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
        logger.exception("Investigation job %s crashed.", investigation_id)
        return False
    logger.info("Investigation job %s finished: %s.", investigation_id, outcome.value)
    return True


async def _discard_worker_runtime() -> None:
    """Close and forget the runtime so the next job rebuilds it with fresh connections."""
    global _worker_runtime
    runtime, _worker_runtime = _worker_runtime, None
    if runtime is None:
        return
    try:
        await runtime.resources.aclose()
    except Exception:
        logger.exception("Could not close the worker runtime after a crash.")


async def _process_records(records: list[Any]) -> list[dict[str, str]]:
    global _worker_runtime
    failures: list[dict[str, str]] = []
    for record in records:
        parsed = _parse_record(record)
        if parsed is None:
            message_id = record.get("messageId") if isinstance(record, dict) else None
            logger.warning("Dropping malformed job queue message %s.", message_id)
            continue
        message_id, job = parsed
        if _worker_runtime is None:
            _worker_runtime = await _open_worker_runtime()
        if not await _process_job(_worker_runtime, job):
            failures.append({"itemIdentifier": message_id})
            await _discard_worker_runtime()
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


def ingest_handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    """EventBridge handler: create an incident from a CloudWatch alarm entering ALARM.

    Errors propagate so EventBridge retries; a duplicate is a normal outcome, not an error.
    """
    _load_environment()
    settings = get_settings()
    with session_factory_provider()() as session:
        service = IncidentIngestionService(
            IncidentRepository(session),
            alarm_tag_reader_factory(),
            settings.ingest_alarm_prefix,
        )
        result = service.ingest_cloudwatch_alarm(event)
    return {"outcome": result.outcome.name}


def demo_handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    """Replay the demo outages through real alarms; EventBridge then ingests them as incidents."""
    _load_environment()
    run_id = str(event.get("run_id") or uuid.uuid4().hex)
    demo_simulator_factory(get_settings()).run(run_id)
    return {"run_id": run_id}


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

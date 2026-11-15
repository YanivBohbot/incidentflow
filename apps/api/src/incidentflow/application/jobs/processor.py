"""Run one investigation job, deciding what to do from the checkpoint, not from the message.

Delivery is at-least-once and the previous worker may have died at any point, so every call
re-derives the next step from the durable LangGraph checkpoint and fences every database
write with the lease token from its claim.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any
from uuid import UUID

from langgraph.types import Command
from sqlalchemy.orm import Session

from incidentflow.agent.orchestration.policies.human_review import (
    jira_write_review_from_interrupt,
)
from incidentflow.domain.investigations.models import Investigation, InvestigationLifecycle
from incidentflow.infrastructure.database.investigation_repository import (
    ClaimedInvestigation,
    InvestigationRepository,
)

logger = logging.getLogger(__name__)

JIRA_OUTCOME_UNKNOWN_MESSAGE = (
    "The worker stopped while an approved Jira write was being executed. Its outcome is "
    "unknown: check Jira before launching a new investigation."
)
MAX_ATTEMPTS_MESSAGE = "The investigation could not complete after {attempts} attempts."
WORKFLOW_FAILED_MESSAGE = "Workflow execution failed before a report was produced."


class JobOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    FAILED = "FAILED"
    # Nothing to do (unknown, terminal, or leased elsewhere), or this worker lost its lease.
    DROPPED = "DROPPED"


_OUTCOME_BY_LIFECYCLE = {
    InvestigationLifecycle.COMPLETED: JobOutcome.COMPLETED,
    InvestigationLifecycle.AWAITING_HUMAN_REVIEW: JobOutcome.AWAITING_HUMAN_REVIEW,
    InvestigationLifecycle.FAILED: JobOutcome.FAILED,
}


class LeaseLostError(RuntimeError):
    """A fenced write matched no row: another worker now owns the investigation."""


def persist_workflow_result(
    repository: InvestigationRepository, claimed: ClaimedInvestigation, result: dict
) -> Investigation:
    """Persist a completed, paused, or failed graph result as product lifecycle state."""
    investigation_id = claimed.investigation.id
    token = claimed.lease_token
    report = result.get("report")
    review = result.get("human_review")
    interrupts = result.get("__interrupt__")
    if interrupts and review is None:
        review = jira_write_review_from_interrupt(interrupts[0].value)
    if interrupts and review is not None:
        persisted = repository.mark_awaiting_human_review(
            investigation_id, report, review, lease_token=token
        )
    elif result.get("investigation_lifecycle") == "completed" and report is not None:
        persisted = repository.complete_investigation(investigation_id, report, lease_token=token)
    else:
        error_message = "; ".join(result.get("errors", [])) or "Investigation workflow failed."
        persisted = repository.fail_investigation(
            investigation_id, error_message, lease_token=token
        )
    if persisted is None:
        raise LeaseLostError("The investigation lease was lost before the result was persisted.")
    return persisted


class InvestigationJobProcessor:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        workflow: Any,
        *,
        lease_seconds: int,
        max_attempts: int,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.workflow = workflow
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.heartbeat_interval_seconds = (
            heartbeat_interval_seconds
            if heartbeat_interval_seconds is not None
            else lease_seconds / 3
        )

    async def process(
        self,
        investigation_id: UUID,
        *,
        keep_alive: Callable[[], Awaitable[None]] | None = None,
    ) -> JobOutcome:
        claimed = await asyncio.to_thread(self._claim, investigation_id)
        if claimed is None:
            return JobOutcome.DROPPED
        if claimed.attempt_count > self.max_attempts:
            return await self._fail(
                claimed, MAX_ATTEMPTS_MESSAGE.format(attempts=self.max_attempts)
            )

        investigation = claimed.investigation
        config = {"configurable": {"thread_id": investigation.workflow_thread_id}}
        snapshot = await self.workflow.aget_state(config)
        values = snapshot.values or {}
        interrupts = [item for task in snapshot.tasks for item in task.interrupts]
        resume = claimed.resume_payload

        if not values and not snapshot.next:
            # 1. Fresh: no checkpoint yet.
            payload: Any = {
                "incident_request": investigation.incident_request,
                "incident_business_status": investigation.incident_business_status,
            }
        elif interrupts and resume and claimed.attempt_count == 1:
            # 2. First attempt of this job: apply the operator's decision.
            payload = Command(
                resume=resume["command_resume"],
                update={"review_events": [resume["review_event"]]},
            )
        elif interrupts:
            # An approved Jira write on a redelivered job may already have run: a crash after
            # the call is indistinguishable from one before it.
            if (
                resume
                and resume.get("review_type") == "JIRA_WRITE"
                and resume.get("decision") == "APPROVE"
            ):
                return await self._fail(claimed, JIRA_OUTCOME_UNKNOWN_MESSAGE)
            # 4. Paused, but not persisted: the previous worker died first. On a reclaim the
            # pending interrupt may be a later one the operator never saw, so a stored
            # decision is never applied to it; the operator is asked again.
            return await self._persist(
                claimed,
                {
                    "__interrupt__": interrupts,
                    "report": values.get("report"),
                    "human_review": values.get("human_review"),
                },
            )
        elif snapshot.next:
            # 3. Continue from the last checkpoint.
            payload = None
        else:
            # 5. Finished, but the previous worker died before persisting the result.
            return await self._persist(claimed, dict(values))

        return await self._run(claimed, payload, config, keep_alive)

    async def _run(
        self,
        claimed: ClaimedInvestigation,
        payload: Any,
        config: dict,
        keep_alive: Callable[[], Awaitable[None]] | None,
    ) -> JobOutcome:
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_loop(claimed, keep_alive, lease_lost))
        try:
            result = await self.workflow.ainvoke(payload, config)
        except Exception:
            logger.exception("Investigation workflow failed before producing a result")
            if lease_lost.is_set():
                return JobOutcome.DROPPED
            return await self._fail(claimed, WORKFLOW_FAILED_MESSAGE)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        if lease_lost.is_set():
            # Another worker owns the job now; its fenced writes win and ours would no-op.
            return JobOutcome.DROPPED
        return await self._persist(claimed, result)

    async def _heartbeat_loop(
        self,
        claimed: ClaimedInvestigation,
        keep_alive: Callable[[], Awaitable[None]] | None,
        lease_lost: asyncio.Event,
    ) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            try:
                renewed = await asyncio.to_thread(self._heartbeat, claimed)
            except Exception:
                logger.exception("Investigation lease heartbeat failed; retrying")
                continue
            if not renewed:
                logger.warning("Investigation lease was lost; the result will be dropped")
                lease_lost.set()
                return
            if keep_alive is not None:
                try:
                    await keep_alive()
                except Exception:
                    logger.exception("Job keep-alive failed; retrying")

    async def _persist(self, claimed: ClaimedInvestigation, result: dict) -> JobOutcome:
        try:
            persisted = await asyncio.to_thread(self._persist_sync, claimed, result)
        except LeaseLostError:
            return JobOutcome.DROPPED
        return _OUTCOME_BY_LIFECYCLE[persisted.lifecycle]

    async def _fail(self, claimed: ClaimedInvestigation, message: str) -> JobOutcome:
        failed = await asyncio.to_thread(self._fail_sync, claimed, message)
        return JobOutcome.FAILED if failed is not None else JobOutcome.DROPPED

    def _claim(self, investigation_id: UUID) -> ClaimedInvestigation | None:
        with self.session_factory() as session:
            return InvestigationRepository(session).claim(
                investigation_id, lease_seconds=self.lease_seconds
            )

    def _heartbeat(self, claimed: ClaimedInvestigation) -> bool:
        with self.session_factory() as session:
            return InvestigationRepository(session).heartbeat(
                claimed.investigation.id, claimed.lease_token, lease_seconds=self.lease_seconds
            )

    def _persist_sync(self, claimed: ClaimedInvestigation, result: dict) -> Investigation:
        with self.session_factory() as session:
            return persist_workflow_result(InvestigationRepository(session), claimed, result)

    def _fail_sync(self, claimed: ClaimedInvestigation, message: str) -> Investigation | None:
        with self.session_factory() as session:
            return InvestigationRepository(session).fail_investigation(
                claimed.investigation.id, message, lease_token=claimed.lease_token
            )

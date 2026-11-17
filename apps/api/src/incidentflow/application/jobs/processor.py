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
RUN_TIMEOUT_MESSAGE = "The investigation did not finish within {seconds} seconds."
DEFAULT_TIMEOUT_SECONDS = 900
WORKFLOW_FAILED_MESSAGE = "Workflow execution failed before a report was produced."


class JobOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    FAILED = "FAILED"
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
    """Run one queued investigation under a lease, resuming from its checkpoint.

    The run deadline fits AWS Lambda's 15-minute cap, so a Lambda can reuse it.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        workflow: Any,
        *,
        lease_seconds: int,
        max_attempts: int,
        heartbeat_interval_seconds: float | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
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
        self.timeout_seconds = timeout_seconds

    async def process(
        self,
        investigation_id: UUID,
        *,
        keep_alive: Callable[[], Awaitable[None]] | None = None,
    ) -> JobOutcome:
        """Claim the investigation, run or resume its workflow, and persist the outcome.

        An approved Jira write is never replayed on a redelivered job, because a crash after
        the call looks the same as one before it; the operator is asked again instead.
        """
        claimed = await asyncio.to_thread(self._claim, investigation_id)
        if claimed is None:
            return JobOutcome.DROPPED
        await self._keep_alive(keep_alive)
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
        approved_jira_write = bool(
            resume
            and resume.get("review_type") == "JIRA_WRITE"
            and resume.get("decision") == "APPROVE"
        )
        runs_approved_jira_write = False

        if not values and not snapshot.next:
            payload: Any = {
                "incident_request": investigation.incident_request,
                "incident_business_status": investigation.incident_business_status,
            }
        elif interrupts and resume and claimed.attempt_count == 1:
            payload = Command(
                resume=resume["command_resume"],
                update={"review_events": [resume["review_event"]]},
            )
            runs_approved_jira_write = approved_jira_write
        elif interrupts:
            if approved_jira_write:
                return await self._fail(claimed, JIRA_OUTCOME_UNKNOWN_MESSAGE)
            return await self._persist(
                claimed,
                {
                    "__interrupt__": interrupts,
                    "report": values.get("report"),
                    "human_review": values.get("human_review"),
                },
            )
        elif snapshot.next:
            payload = None
        else:
            return await self._persist(claimed, dict(values))

        return await self._run(
            claimed,
            payload,
            config,
            keep_alive,
            runs_approved_jira_write=runs_approved_jira_write,
        )

    async def _run(
        self,
        claimed: ClaimedInvestigation,
        payload: Any,
        config: dict,
        keep_alive: Callable[[], Awaitable[None]] | None,
        *,
        runs_approved_jira_write: bool,
    ) -> JobOutcome:
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_loop(claimed, keep_alive, lease_lost))
        deadline = asyncio.timeout(self.timeout_seconds)
        try:
            async with deadline:
                result = await self.workflow.ainvoke(payload, config)
        except Exception as error:
            if isinstance(error, TimeoutError) and deadline.expired():
                logger.error("Investigation workflow exceeded %s seconds", self.timeout_seconds)
                if lease_lost.is_set():
                    return JobOutcome.DROPPED
                message = (
                    JIRA_OUTCOME_UNKNOWN_MESSAGE
                    if runs_approved_jira_write
                    else RUN_TIMEOUT_MESSAGE.format(seconds=f"{self.timeout_seconds:g}")
                )
                return await self._fail(claimed, message)
            logger.exception("Investigation workflow failed before producing a result")
            if lease_lost.is_set():
                return JobOutcome.DROPPED
            return await self._fail(claimed, WORKFLOW_FAILED_MESSAGE)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        if lease_lost.is_set():
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
            await self._keep_alive(keep_alive)

    @staticmethod
    async def _keep_alive(keep_alive: Callable[[], Awaitable[None]] | None) -> None:
        if keep_alive is None:
            return
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

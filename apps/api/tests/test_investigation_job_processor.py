"""The job processor decides what to run from the checkpoint, so any retry is safe."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agent_fakes import ApprovalGatedSupervisor, scripted_model
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.agent.findings import InvestigationReport
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)
from incidentflow.application.jobs.processor import (
    JIRA_OUTCOME_UNKNOWN_MESSAGE,
    MAX_ATTEMPTS_MESSAGE,
    InvestigationJobProcessor,
    JobOutcome,
)
from incidentflow.domain.human_review.models import HumanReviewType
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationLifecycle,
    utc_now,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
REPORT = InvestigationReport(summary="A Jira issue was considered.", confidence=0.8)
APPROVE_PAYLOAD = {
    "command_resume": {"decisions": [{"type": "approve"}]},
    "review_event": {"review": None, "decision": {"decision": "APPROVE", "actor": "op"}},
    "review_type": "JIRA_WRITE",
    "decision": "APPROVE",
}
REJECT_PAYLOAD = {
    "command_resume": {"decisions": [{"type": "reject", "message": "Not now."}]},
    "review_event": {"review": None, "decision": {"decision": "REJECT", "actor": "op"}},
    "review_type": "JIRA_WRITE",
    "decision": "REJECT",
}


class WorkerDied(BaseException):
    """Stands in for a process kill: escapes the node error handler like a real crash."""


class ReportingSupervisor:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _payload: dict, *, config: dict) -> dict:
        self.calls += 1
        return {"structured_response": REPORT}


class ThrowingSupervisor:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _payload: dict, *, config: dict) -> dict:
        self.calls += 1
        raise ValueError("The supervisor could not parse its own output.")


class DiesAfterJiraWriteSupervisor(ApprovalGatedSupervisor):
    """Executes the approved write, then the worker dies before the node returns."""

    async def ainvoke(self, payload: dict, *, config: dict) -> dict:
        result = await super().ainvoke(payload, config=config)
        if len(self.resume_values) == 1:
            raise WorkerDied()
        return result


class TwoJiraWritesSupervisor:
    """Pauses for a Jira issue, then pauses again for a Jira comment."""

    def __init__(self) -> None:
        self.resume_values: list[object] = []

    async def ainvoke(self, _payload: dict, *, config: dict) -> dict:
        for name, arguments in (
            ("createJiraIssue", {"summary": "Payment API errors"}),
            ("addOrEditJiraIssueComment", {"commentBody": "Investigating."}),
        ):
            decision = interrupt({"action_requests": [{"name": name, "arguments": arguments}]})
            self.resume_values.append(decision)
        return {"structured_response": REPORT}


class Harness:
    def __init__(self, supervisor: object, **processor_options: float) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.supervisor = supervisor
        self.workflow = build_investigation_workflow(supervisor, checkpointer=InMemorySaver())
        self.processor = InvestigationJobProcessor(
            self.session_factory,
            self.workflow,
            lease_seconds=LEASE_SECONDS,
            max_attempts=MAX_ATTEMPTS,
            **processor_options,
        )

    def create(self) -> Investigation:
        with self.session_factory() as session:
            incident = IncidentORM(
                id=uuid4(),
                title="Payment API",
                description="HTTP 500s.",
                priority=IncidentPriority.HIGH,
            )
            session.add(incident)
            session.commit()
            return InvestigationRepository(session).create_investigation(
                InvestigationCreate(
                    incident_id=incident.id,
                    incident_request="Investigate Payment API HTTP 500 errors.",
                    incident_business_status="OPEN",
                )
            )

    def get(self, investigation_id: UUID) -> Investigation:
        with self.session_factory() as session:
            investigation = InvestigationRepository(session).get_investigation(investigation_id)
        assert investigation is not None
        return investigation

    def request_resume(self, investigation_id: UUID, payload: dict) -> None:
        with self.session_factory() as session:
            assert InvestigationRepository(session).request_resume(investigation_id, payload)

    def claim_and_die(self, investigation_id: UUID, *, seconds_ago: int = 1000) -> None:
        """A worker claimed the job in the past and died; its lease has expired by now."""
        with self.session_factory() as session:
            claimed = InvestigationRepository(session).claim(
                investigation_id,
                lease_seconds=LEASE_SECONDS,
                now=utc_now() - timedelta(seconds=seconds_ago),
            )
        assert claimed is not None

    def pending_resume_payload(self, investigation_id: UUID) -> dict | None:
        with self.session_factory() as session:
            return session.get(InvestigationORM, investigation_id).pending_resume_payload

    def expire_lease(self, investigation_id: UUID) -> None:
        with self.session_factory() as session:
            session.execute(
                update(InvestigationORM)
                .where(InvestigationORM.id == investigation_id)
                .values(lease_expires_at=utc_now() - timedelta(seconds=1))
            )
            session.commit()

    def steal_lease(self, investigation_id: UUID) -> None:
        with self.session_factory() as session:
            session.execute(
                update(InvestigationORM)
                .where(InvestigationORM.id == investigation_id)
                .values(lease_token="another-worker")
            )
            session.commit()

    def config(self, investigation: Investigation) -> dict:
        return {"configurable": {"thread_id": investigation.workflow_thread_id}}

    def initial_input(self, investigation: Investigation) -> dict:
        return {
            "incident_request": investigation.incident_request,
            "incident_business_status": investigation.incident_business_status,
        }


@pytest.mark.anyio
async def test_fresh_job_completes() -> None:
    harness = Harness(ReportingSupervisor())
    investigation = harness.create()

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.COMPLETED
    persisted = harness.get(investigation.id)
    assert persisted.lifecycle is InvestigationLifecycle.COMPLETED
    assert persisted.report == REPORT
    assert harness.supervisor.calls == 1


@pytest.mark.anyio
async def test_jira_pause_then_resume_completes() -> None:
    supervisor = ApprovalGatedSupervisor(REPORT)
    harness = Harness(supervisor)
    investigation = harness.create()

    assert await harness.processor.process(investigation.id) is JobOutcome.AWAITING_HUMAN_REVIEW
    paused = harness.get(investigation.id)
    assert paused.human_review is not None
    assert paused.human_review.review_type is HumanReviewType.JIRA_WRITE
    assert paused.human_review.draft["tool_name"] == "createJiraIssue"

    harness.request_resume(investigation.id, APPROVE_PAYLOAD)
    assert await harness.processor.process(investigation.id) is JobOutcome.COMPLETED

    assert supervisor.resume_values == [{"decisions": [{"type": "approve"}]}]
    assert harness.get(investigation.id).lifecycle is InvestigationLifecycle.COMPLETED
    state = await harness.workflow.aget_state(harness.config(investigation))
    assert state.values["review_events"] == [APPROVE_PAYLOAD["review_event"]]


@pytest.mark.anyio
async def test_reclaimed_approved_jira_resume_is_not_rerun() -> None:
    supervisor = ApprovalGatedSupervisor(REPORT)
    harness = Harness(supervisor)
    investigation = harness.create()
    await harness.processor.process(investigation.id)
    harness.request_resume(investigation.id, APPROVE_PAYLOAD)
    harness.claim_and_die(investigation.id)

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.FAILED
    failed = harness.get(investigation.id)
    assert failed.lifecycle is InvestigationLifecycle.FAILED
    assert failed.error_message == JIRA_OUTCOME_UNKNOWN_MESSAGE
    assert supervisor.resume_values == []


@pytest.mark.anyio
async def test_worker_death_after_approved_jira_write_is_not_rerun() -> None:
    """The dangerous crash: the write ran, the node never returned, the job is redelivered."""
    supervisor = DiesAfterJiraWriteSupervisor(REPORT)
    harness = Harness(supervisor)
    investigation = harness.create()
    await harness.processor.process(investigation.id)
    harness.request_resume(investigation.id, APPROVE_PAYLOAD)
    with pytest.raises(WorkerDied):
        await harness.processor.process(investigation.id)
    assert len(supervisor.resume_values) == 1
    harness.expire_lease(investigation.id)

    # The pending interrupt is still visible: the resumed node never produced a checkpoint.
    snapshot = await harness.workflow.aget_state(harness.config(investigation))
    assert [i for task in snapshot.tasks for i in task.interrupts]

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.FAILED
    assert harness.get(investigation.id).error_message == JIRA_OUTCOME_UNKNOWN_MESSAGE
    assert len(supervisor.resume_values) == 1


@pytest.mark.anyio
async def test_reclaimed_rejected_jira_resume_is_asked_again() -> None:
    supervisor = ApprovalGatedSupervisor(REPORT)
    harness = Harness(supervisor)
    investigation = harness.create()
    await harness.processor.process(investigation.id)
    harness.request_resume(investigation.id, REJECT_PAYLOAD)
    harness.claim_and_die(investigation.id)

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.AWAITING_HUMAN_REVIEW
    paused = harness.get(investigation.id)
    assert paused.human_review is not None
    assert paused.human_review.draft["tool_name"] == "createJiraIssue"
    assert supervisor.resume_values == []
    assert harness.pending_resume_payload(investigation.id) is None


@pytest.mark.anyio
async def test_reclaim_never_applies_old_decision_to_a_new_interrupt() -> None:
    supervisor = TwoJiraWritesSupervisor()
    harness = Harness(supervisor)
    investigation = harness.create()
    assert await harness.processor.process(investigation.id) is JobOutcome.AWAITING_HUMAN_REVIEW
    harness.request_resume(investigation.id, REJECT_PAYLOAD)
    # A worker claimed the job, resumed the graph to its second pause, and died before
    # persisting that pause.
    harness.claim_and_die(investigation.id)
    await harness.workflow.ainvoke(
        Command(
            resume=REJECT_PAYLOAD["command_resume"],
            update={"review_events": [REJECT_PAYLOAD["review_event"]]},
        ),
        harness.config(investigation),
    )
    assert supervisor.resume_values == [REJECT_PAYLOAD["command_resume"]]

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.AWAITING_HUMAN_REVIEW
    paused = harness.get(investigation.id)
    assert paused.human_review is not None
    assert paused.human_review.draft["tool_name"] == "addOrEditJiraIssueComment"
    assert supervisor.resume_values == [REJECT_PAYLOAD["command_resume"]]


@pytest.mark.anyio
async def test_paused_checkpoint_is_persisted_without_running() -> None:
    supervisor = ApprovalGatedSupervisor(REPORT)
    harness = Harness(supervisor)
    investigation = harness.create()
    # A previous worker reached the pause and died before persisting it.
    await harness.workflow.ainvoke(
        harness.initial_input(investigation), harness.config(investigation)
    )
    harness.claim_and_die(investigation.id)

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.AWAITING_HUMAN_REVIEW
    paused = harness.get(investigation.id)
    assert paused.human_review is not None
    assert paused.human_review.review_type is HumanReviewType.JIRA_WRITE
    assert supervisor.calls == 1


@pytest.mark.anyio
async def test_finished_checkpoint_is_persisted_without_running() -> None:
    supervisor = ReportingSupervisor()
    harness = Harness(supervisor)
    investigation = harness.create()
    await harness.workflow.ainvoke(
        harness.initial_input(investigation), harness.config(investigation)
    )
    harness.claim_and_die(investigation.id)

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.COMPLETED
    assert harness.get(investigation.id).report == REPORT
    assert supervisor.calls == 1


@pytest.mark.anyio
async def test_nested_agent_interrupt_is_visible_in_checkpoint_tasks() -> None:
    """A real create_agent with HumanInTheLoopMiddleware pauses one subgraph level down."""
    writes: list[str] = []

    @tool
    def createJiraIssue(summary: str) -> str:
        """Create a Jira issue."""
        writes.append(summary)
        return "PAY-1"

    agent = create_agent(
        scripted_model([[("createJiraIssue", {"summary": "Payment API errors"})], "done"]),
        tools=[createJiraIssue],
        middleware=[HumanInTheLoopMiddleware(interrupt_on={"createJiraIssue": True})],
    )
    harness = Harness(agent)
    investigation = harness.create()
    await harness.workflow.ainvoke(
        harness.initial_input(investigation), harness.config(investigation)
    )

    snapshot = await harness.workflow.aget_state(harness.config(investigation))
    assert snapshot.next == ("investigate",)
    assert [task.name for task in snapshot.tasks if task.interrupts] == ["investigate"]

    harness.claim_and_die(investigation.id)
    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.AWAITING_HUMAN_REVIEW
    review = harness.get(investigation.id).human_review
    assert review is not None and review.draft["tool_name"] == "createJiraIssue"
    assert review.draft["arguments"] == {"summary": "Payment API errors"}
    assert writes == []


@pytest.mark.anyio
async def test_max_attempts_fails() -> None:
    supervisor = ReportingSupervisor()
    harness = Harness(supervisor)
    investigation = harness.create()
    for seconds_ago in (1000, 650, 301):
        harness.claim_and_die(investigation.id, seconds_ago=seconds_ago)

    outcome = await harness.processor.process(investigation.id)

    assert outcome is JobOutcome.FAILED
    failed = harness.get(investigation.id)
    assert failed.error_message == MAX_ATTEMPTS_MESSAGE.format(attempts=MAX_ATTEMPTS)
    assert supervisor.calls == 0


@pytest.mark.anyio
async def test_workflow_exception_fails_and_is_not_retried() -> None:
    supervisor = ThrowingSupervisor()
    harness = Harness(supervisor)
    investigation = harness.create()

    assert await harness.processor.process(investigation.id) is JobOutcome.FAILED
    assert harness.get(investigation.id).lifecycle is InvestigationLifecycle.FAILED
    assert await harness.processor.process(investigation.id) is JobOutcome.DROPPED
    assert supervisor.calls == 1


@pytest.mark.anyio
async def test_exception_escaping_the_workflow_fails_the_investigation() -> None:
    class BrokenWorkflow:
        async def aget_state(self, _config: dict) -> SimpleNamespace:
            return SimpleNamespace(values={}, next=(), tasks=())

        async def ainvoke(self, _payload: object, _config: dict) -> dict:
            raise RuntimeError("checkpointer unavailable")

    harness = Harness(ReportingSupervisor())
    investigation = harness.create()
    processor = InvestigationJobProcessor(
        harness.session_factory,
        BrokenWorkflow(),
        lease_seconds=LEASE_SECONDS,
        max_attempts=MAX_ATTEMPTS,
    )

    assert await processor.process(investigation.id) is JobOutcome.FAILED
    failed = harness.get(investigation.id)
    assert failed.error_message == "Workflow execution failed before a report was produced."


@pytest.mark.anyio
async def test_unknown_or_terminal_investigation_is_dropped() -> None:
    harness = Harness(ReportingSupervisor())
    assert await harness.processor.process(uuid4()) is JobOutcome.DROPPED

    investigation = harness.create()
    assert await harness.processor.process(investigation.id) is JobOutcome.COMPLETED
    assert await harness.processor.process(investigation.id) is JobOutcome.DROPPED


@pytest.mark.anyio
async def test_heartbeat_keeps_the_message_alive_while_the_workflow_runs() -> None:
    class SlowSupervisor(ReportingSupervisor):
        async def ainvoke(self, payload: dict, *, config: dict) -> dict:
            await asyncio.sleep(0.2)
            return await super().ainvoke(payload, config=config)

    harness = Harness(SlowSupervisor(), heartbeat_interval_seconds=0.02)
    investigation = harness.create()
    keep_alive_calls = 0

    async def keep_alive() -> None:
        nonlocal keep_alive_calls
        keep_alive_calls += 1

    assert await harness.processor.process(investigation.id, keep_alive=keep_alive) is (
        JobOutcome.COMPLETED
    )
    assert keep_alive_calls >= 1


@pytest.mark.anyio
async def test_lost_lease_drops_the_result_without_persisting() -> None:
    holder: dict[str, Harness] = {}

    class LeaseStolenSupervisor(ReportingSupervisor):
        async def ainvoke(self, payload: dict, *, config: dict) -> dict:
            harness = holder["harness"]
            harness.steal_lease(UUID(config["configurable"]["thread_id"].split(":", 1)[1]))
            await asyncio.sleep(0.2)
            return await super().ainvoke(payload, config=config)

    harness = Harness(LeaseStolenSupervisor(), heartbeat_interval_seconds=0.02)
    holder["harness"] = harness
    investigation = harness.create()

    assert await harness.processor.process(investigation.id) is JobOutcome.DROPPED
    persisted = harness.get(investigation.id)
    assert persisted.lifecycle is InvestigationLifecycle.RUNNING
    assert persisted.report is None


@pytest.mark.anyio
async def test_fenced_write_after_lost_lease_is_dropped() -> None:
    """Even without a heartbeat in between, the final write is fenced by the token."""
    holder: dict[str, Harness] = {}

    class LeaseStolenSupervisor(ReportingSupervisor):
        async def ainvoke(self, payload: dict, *, config: dict) -> dict:
            harness = holder["harness"]
            harness.steal_lease(UUID(config["configurable"]["thread_id"].split(":", 1)[1]))
            return await super().ainvoke(payload, config=config)

    harness = Harness(LeaseStolenSupervisor())
    holder["harness"] = harness
    investigation = harness.create()

    assert await harness.processor.process(investigation.id) is JobOutcome.DROPPED
    assert harness.get(investigation.id).lifecycle is InvestigationLifecycle.RUNNING

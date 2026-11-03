import logging
from typing import Any
from uuid import UUID

from langgraph.types import Command

from incidentflow.agent.orchestration.policies.human_review import (
    jira_tool_resume_payload,
    jira_write_review_from_interrupt,
)
from incidentflow.agent.orchestration.trace import build_investigation_trace
from incidentflow.core.operational_metrics import OperationalMetrics
from incidentflow.domain.human_review.models import HumanReviewDecision, HumanReviewType
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationLifecycle,
    InvestigationStart,
    InvestigationTraceStep,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)

logger = logging.getLogger(__name__)


class InvestigationService:
    def __init__(
        self,
        repository: InvestigationRepository,
        incident_repository: IncidentRepository,
        workflow: Any,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        self.repository = repository
        self.incident_repository = incident_repository
        self.workflow = workflow
        self.metrics = metrics

    async def start_investigation(self, data: InvestigationStart) -> Investigation | None:
        incident = self.incident_repository.get_incident(data.incident_id)
        if incident is None:
            return None
        return await self.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request=data.incident_request,
                incident_business_status=incident.status.value,
            )
        )

    def get_investigation(self, investigation_id: UUID) -> Investigation | None:
        return self.repository.get_investigation(investigation_id)

    def list_investigations(self) -> list[Investigation]:
        return self.repository.list_investigations()

    async def run_investigation(self, data: InvestigationCreate) -> Investigation:
        investigation = self.repository.create_investigation(data)
        running = self.repository.mark_running(investigation.id)

        if running is None:
            raise RuntimeError("Created investigation could not be marked as running.")

        try:
            result = await self.workflow.ainvoke(
                {
                    "incident_request": running.incident_request,
                    "incident_business_status": running.incident_business_status,
                },
                config={"configurable": {"thread_id": running.workflow_thread_id}},
            )
        except Exception:
            logger.exception("Investigation workflow failed before producing a result")
            failed = self.repository.fail_investigation(
                running.id,
                "Workflow execution failed before a report was produced.",
            )
            if failed is None:
                raise RuntimeError("Failed investigation could not be persisted.")
            self._record_lifecycle(failed.lifecycle.value)
            return failed

        return self._persist_workflow_result(running, result)

    async def resume_human_review(
        self, investigation_id: UUID, decision: HumanReviewDecision
    ) -> Investigation | None:
        """Resume the paused graph with the same durable investigation thread."""
        investigation = self.repository.get_investigation(investigation_id)
        if investigation is None or investigation.lifecycle is not InvestigationLifecycle.AWAITING_HUMAN_REVIEW:
            return None
        resume_payload = decision.model_dump(mode="json")
        if (
            investigation.human_review
            and investigation.human_review.review_type is HumanReviewType.JIRA_WRITE
        ):
            # Raises HumanReviewEditError before the graph resumes, so a rejected edit
            # leaves the investigation paused and the operator can correct it.
            resume_payload = jira_tool_resume_payload(decision, investigation.human_review)
        try:
            # Record the pause and the decision in the graph state so the trace can show them.
            review_event = {
                "review": investigation.human_review.model_dump(mode="json")
                if investigation.human_review
                else None,
                "decision": decision.model_dump(mode="json"),
            }
            result = await self.workflow.ainvoke(
                Command(resume=resume_payload, update={"review_events": [review_event]}),
                config={"configurable": {"thread_id": investigation.workflow_thread_id}},
            )
        except Exception:
            logger.exception("Investigation workflow failed while resuming human review")
            failed = self.repository.fail_investigation(
                investigation.id,
                "Workflow execution failed while processing the human review decision.",
            )
            if failed is None:
                raise RuntimeError("Failed investigation could not be persisted.")
            self._record_lifecycle(failed.lifecycle.value)
            return failed
        return self._persist_workflow_result(investigation, result)

    async def get_investigation_trace(
        self, investigation_id: UUID
    ) -> list[InvestigationTraceStep] | None:
        """Rebuild the agent timeline from the durable LangGraph checkpoint."""
        investigation = self.repository.get_investigation(investigation_id)
        if investigation is None:
            return None
        config = {"configurable": {"thread_id": investigation.workflow_thread_id}}
        snapshot = await self.workflow.aget_state(config)
        values = dict(snapshot.values or {})
        # While the supervisor runs or a Jira write is paused, the investigate node has not
        # returned: the supervisor's messages so far live in its own subgraph checkpoint.
        supervisor_messages, subagent_runs = await self._latest_agent_messages(config)
        if len(supervisor_messages) > len(values.get("messages", [])):
            values["messages"] = supervisor_messages
        pending = (
            investigation.human_review
            if investigation.lifecycle is InvestigationLifecycle.AWAITING_HUMAN_REVIEW
            else None
        )
        return build_investigation_trace(values, pending, subagent_runs)

    async def _latest_agent_messages(self, config: dict) -> tuple[list[Any], list[list[Any]]]:
        """Read the newest checkpoint of the supervisor and of each specialist agent.

        The supervisor runs under "investigate:<task>". Each specialist create_agent runs
        inside a supervisor tool, one level deeper: "investigate:<task>|tools:<task>".
        """
        checkpointer = getattr(self.workflow, "checkpointer", None)
        if checkpointer is None or not hasattr(checkpointer, "alist"):
            return [], []
        latest: dict[str, Any] = {}
        async for checkpoint in checkpointer.alist(config):  # newest first
            namespace = checkpoint.config["configurable"].get("checkpoint_ns", "")
            if namespace.startswith("investigate:") and namespace not in latest:
                latest[namespace] = checkpoint
        supervisor: list[Any] = []
        runs: list[tuple[str, list[Any]]] = []
        for namespace, checkpoint in latest.items():
            messages = checkpoint.checkpoint["channel_values"].get("messages", [])
            depth = namespace.count("|")
            if depth == 0 and not supervisor:
                supervisor = messages
            elif depth == 1:
                runs.append((checkpoint.checkpoint.get("ts", ""), messages))
        return supervisor, [messages for _ts, messages in sorted(runs, key=lambda run: run[0])]

    def _persist_workflow_result(self, investigation: Investigation, result: dict) -> Investigation:
        """Persist a completed, paused, or failed graph result as product lifecycle state."""
        report = result.get("report")
        review = result.get("human_review")
        interrupts = result.get("__interrupt__")
        if interrupts and review is None:
            review = jira_write_review_from_interrupt(interrupts[0].value)
        if interrupts and review is not None:
            awaiting = self.repository.mark_awaiting_human_review(investigation.id, report, review)
            if awaiting is None:
                raise RuntimeError("Paused investigation could not be persisted.")
            self._record_lifecycle(awaiting.lifecycle.value)
            return awaiting
        if result.get("investigation_lifecycle") == "completed" and report is not None:
            completed = self.repository.complete_investigation(investigation.id, report)
            if completed is None:
                raise RuntimeError("Completed investigation could not be persisted.")
            self._record_lifecycle(completed.lifecycle.value)
            return completed

        error_message = "; ".join(result.get("errors", [])) or "Investigation workflow failed."
        failed = self.repository.fail_investigation(investigation.id, error_message)
        if failed is None:
            raise RuntimeError("Failed investigation could not be persisted.")
        self._record_lifecycle(failed.lifecycle.value)
        return failed

    def _record_lifecycle(self, lifecycle: str) -> None:
        """Record the final durable state without collecting incident content."""
        if self.metrics is not None:
            self.metrics.record_investigation(lifecycle)

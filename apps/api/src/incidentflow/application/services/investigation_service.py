import logging
from typing import Any
from uuid import UUID

from langgraph.types import Command

from incidentflow.agent.orchestration.policies.human_review import (
    jira_tool_resume_payload,
    jira_write_review_from_interrupt,
)
from incidentflow.core.operational_metrics import OperationalMetrics
from incidentflow.domain.human_review.models import HumanReviewDecision, HumanReviewType
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationLifecycle,
    InvestigationStart,
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
        try:
            resume_payload = decision.model_dump(mode="json")
            if (
                investigation.human_review
                and investigation.human_review.review_type is HumanReviewType.JIRA_WRITE
            ):
                resume_payload = jira_tool_resume_payload(decision)
            result = await self.workflow.ainvoke(
                Command(resume=resume_payload),
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

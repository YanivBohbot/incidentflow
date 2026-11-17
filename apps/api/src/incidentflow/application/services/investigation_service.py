"""Investigation use cases: queue runs, resume after human review, read traces."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from incidentflow.agent.orchestration.policies.human_review import jira_tool_resume_payload
from incidentflow.agent.orchestration.trace import build_investigation_trace
from incidentflow.application.jobs.queue import JobQueue
from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.human_review.models import HumanReviewDecision, HumanReviewType
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationLifecycle,
    InvestigationStart,
    InvestigationTraceStep,
)
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    START_BLOCKING_LIFECYCLES,
    InvestigationRepository,
    is_active_investigation_conflict,
)

logger = logging.getLogger(__name__)


class InvestigationAlreadyActiveError(Exception):
    """The incident already has a PENDING, RUNNING, or AWAITING_HUMAN_REVIEW investigation."""

    def __init__(self, investigation_id: UUID) -> None:
        super().__init__(f"Investigation {investigation_id} is already active.")
        self.investigation_id = investigation_id


class InvestigationService:
    """Queue investigations, resume them after review, and rebuild their trace."""

    def __init__(
        self,
        repository: InvestigationRepository,
        incident_repository: IncidentRepository,
        queue: JobQueue,
        workflow: Any,
        *,
        events: IncidentEventRepository | None = None,
    ) -> None:
        self.repository = repository
        self.events = events
        self.incident_repository = incident_repository
        self.queue = queue
        self.workflow = workflow

    def start_investigation(
        self, data: InvestigationStart, *, actor: str = "system"
    ) -> Investigation | None:
        """Queue an investigation as PENDING, or refuse when the incident already has one active."""
        incident = self.incident_repository.get_incident(data.incident_id)
        if incident is None:
            return None
        if self.repository.has_active_investigation(incident.id):
            raise self._already_active(incident.id)
        try:
            investigation = self.repository.create_investigation(
                InvestigationCreate(
                    incident_id=incident.id,
                    incident_request=data.incident_request,
                    incident_business_status=incident.status.value,
                )
            )
        except IntegrityError as error:
            if not is_active_investigation_conflict(error):
                raise
            raise self._already_active(incident.id) from error
        if self.events is not None:
            self.events.record(
                IncidentEventKind.INVESTIGATION_STARTED,
                incident_id=incident.id,
                investigation_id=investigation.id,
                actor=actor,
                summary=f"Investigation started by {actor}",
            )
        self._enqueue(investigation.id)
        return investigation

    def _already_active(
        self, incident_id: UUID, *, excluding: UUID | None = None
    ) -> InvestigationAlreadyActiveError:
        active = next(
            (
                item
                for item in self.repository.list_for_incident(incident_id)
                if item.lifecycle in START_BLOCKING_LIFECYCLES and item.id != excluding
            ),
            None,
        )
        return InvestigationAlreadyActiveError(active.id if active else incident_id)

    def get_investigation(self, investigation_id: UUID) -> Investigation | None:
        return self.repository.get_investigation(investigation_id)

    def list_investigations(self) -> list[Investigation]:
        return self.repository.list_investigations()

    def request_human_review_resume(
        self, investigation_id: UUID, decision: HumanReviewDecision
    ) -> Investigation | None:
        """Store the operator decision, move the row back to PENDING, and enqueue the job."""
        investigation = self.repository.get_investigation(investigation_id)
        if (
            investigation is None
            or investigation.lifecycle is not InvestigationLifecycle.AWAITING_HUMAN_REVIEW
        ):
            return None
        review = investigation.human_review
        command_resume = decision.model_dump(mode="json")
        if review and review.review_type is HumanReviewType.JIRA_WRITE:
            command_resume = jira_tool_resume_payload(decision, review)
        payload = {
            "command_resume": command_resume,
            "review_event": {
                "review": review.model_dump(mode="json") if review else None,
                "decision": decision.model_dump(mode="json"),
            },
            "review_type": review.review_type.value if review else None,
            "decision": decision.decision.value,
        }
        try:
            resumed = self.repository.request_resume(investigation_id, payload)
        except IntegrityError as error:
            if not is_active_investigation_conflict(error):
                raise
            raise self._already_active(
                investigation.incident_id, excluding=investigation_id
            ) from error
        if resumed is None:
            return None
        if self.events is not None:
            self._record_decision(resumed, review, decision)
        self._enqueue(resumed.id)
        return resumed

    def _record_decision(
        self, investigation: Investigation, review: Any, decision: HumanReviewDecision
    ) -> None:
        tool_name = (review.draft or {}).get("tool_name") if review else None
        subject = "Jira write" if tool_name else "report review"
        verb = {"APPROVE": "approved", "REJECT": "rejected"}.get(
            decision.decision.value, "sent back for information"
        )
        details = {"decision": decision.decision.value, "reason": decision.reason}
        if review:
            details["review_type"] = review.review_type.value
        if tool_name:
            details["tool_name"] = tool_name
        arguments = (review.draft or {}).get("arguments") or (review.draft or {}).get("tool_args")
        if isinstance(arguments, dict) and arguments.get("projectKey"):
            details["project_key"] = str(arguments["projectKey"])
        self.events.record(
            IncidentEventKind.REVIEW_DECIDED,
            incident_id=investigation.incident_id,
            investigation_id=investigation.id,
            actor=decision.actor,
            summary=f"{subject.capitalize()} {verb} by {decision.actor}",
            details=details,
        )

    def _enqueue(self, investigation_id: UUID) -> None:
        """Send the job after the commit; a failed send is repaired by the sweeper."""
        try:
            self.queue.send(investigation_id)
        except Exception:
            logger.exception("Could not enqueue investigation job; the sweeper will re-send it")

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
        async for checkpoint in checkpointer.alist(config):
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

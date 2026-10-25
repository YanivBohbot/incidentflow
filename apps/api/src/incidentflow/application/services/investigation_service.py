from typing import Any
from uuid import UUID

from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationStart,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)


class InvestigationService:
    def __init__(
        self,
        repository: InvestigationRepository,
        incident_repository: IncidentRepository,
        workflow: Any,
    ) -> None:
        self.repository = repository
        self.incident_repository = incident_repository
        self.workflow = workflow

    def start_investigation(self, data: InvestigationStart) -> Investigation | None:
        incident = self.incident_repository.get_incident(data.incident_id)
        if incident is None:
            return None
        return self.run_investigation(
            InvestigationCreate(
                incident_id=incident.id,
                incident_request=data.incident_request,
                incident_business_status=incident.status.value,
            )
        )

    def get_investigation(self, investigation_id: UUID) -> Investigation | None:
        return self.repository.get_investigation(investigation_id)

    def run_investigation(self, data: InvestigationCreate) -> Investigation:
        investigation = self.repository.create_investigation(data)
        running = self.repository.mark_running(investigation.id)

        if running is None:
            raise RuntimeError("Created investigation could not be marked as running.")

        try:
            result = self.workflow.invoke(
                {
                    "incident_request": running.incident_request,
                    "incident_business_status": running.incident_business_status,
                },
                config={"configurable": {"thread_id": running.workflow_thread_id}},
            )
        except Exception:
            self.repository.fail_investigation(
                running.id,
                "Workflow execution failed before a report was produced.",
            )
            raise

        report = result["report"]
        if result["investigation_lifecycle"] == "completed" and report is not None:
            completed = self.repository.complete_investigation(running.id, report)
            if completed is None:
                raise RuntimeError("Completed investigation could not be persisted.")
            return completed

        error_message = "; ".join(result["errors"]) or "Investigation workflow failed."
        failed = self.repository.fail_investigation(running.id, error_message)
        if failed is None:
            raise RuntimeError("Failed investigation could not be persisted.")
        return failed

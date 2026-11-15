from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from incidentflow.agent.findings import InvestigationReport
from incidentflow.domain.human_review.models import HumanReview
from incidentflow.domain.investigations.models import (
    Investigation,
    InvestigationCreate,
    InvestigationLifecycle,
    utc_now,
)
from incidentflow.infrastructure.database.models import InvestigationORM

RUNNING = InvestigationLifecycle.RUNNING
PENDING = InvestigationLifecycle.PENDING


@dataclass(frozen=True)
class ClaimedInvestigation:
    """A successful claim: the fencing token every later write must present."""

    investigation: Investigation
    lease_token: str
    attempt_count: int
    resume_payload: dict | None


class InvestigationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def to_domain(orm: InvestigationORM) -> Investigation:
        report = (
            InvestigationReport.model_validate(orm.report_payload)
            if orm.report_payload is not None
            else None
        )
        human_review = (
            HumanReview.model_validate(orm.pending_human_review_payload)
            if orm.pending_human_review_payload is not None
            else None
        )
        return Investigation.model_validate(
            {
                "id": orm.id,
                "incident_id": orm.incident_id,
                "incident_request": orm.incident_request,
                "incident_business_status": orm.incident_business_status,
                "lifecycle": orm.lifecycle,
                "workflow_thread_id": orm.workflow_thread_id,
                "report": report,
                "human_review": human_review,
                "error_message": orm.error_message,
                "created_at": orm.created_at,
                "updated_at": orm.updated_at,
            }
        )

    def create_investigation(self, data: InvestigationCreate) -> Investigation:
        investigation_id = uuid4()
        orm = InvestigationORM(
            id=investigation_id,
            incident_id=data.incident_id,
            incident_request=data.incident_request,
            incident_business_status=data.incident_business_status,
            workflow_thread_id=f"investigation:{investigation_id}",
        )
        self.session.add(orm)
        self.session.commit()
        self.session.refresh(orm)
        return self.to_domain(orm)

    def get_investigation(self, investigation_id: UUID) -> Investigation | None:
        orm = self.session.get(InvestigationORM, investigation_id)
        if orm is None:
            return None
        return self.to_domain(orm)

    def list_for_incident(self, incident_id: UUID) -> list[Investigation]:
        statement = (
            select(InvestigationORM)
            .where(InvestigationORM.incident_id == incident_id)
            .order_by(InvestigationORM.created_at.desc())
        )
        return [self.to_domain(orm) for orm in self.session.scalars(statement).all()]

    def list_investigations(self) -> list[Investigation]:
        statement = select(InvestigationORM).order_by(InvestigationORM.created_at.desc())
        return [self.to_domain(orm) for orm in self.session.scalars(statement).all()]

    def has_active_investigation(self, incident_id: UUID) -> bool:
        statement = (
            select(InvestigationORM.id)
            .where(
                InvestigationORM.incident_id == incident_id,
                InvestigationORM.lifecycle.in_([PENDING, RUNNING]),
            )
            .limit(1)
        )
        return self.session.scalars(statement).first() is not None

    def _apply(self, investigation_id: UUID, *conditions, **values) -> Investigation | None:
        """Run one conditional UPDATE; return the re-read row only if it matched."""
        result = self.session.execute(
            update(InvestigationORM)
            .where(InvestigationORM.id == investigation_id, *conditions)
            .values(**values)
        )
        self.session.commit()
        if result.rowcount != 1:
            return None
        self.session.expire_all()
        return self.get_investigation(investigation_id)

    def claim(
        self, investigation_id: UUID, *, lease_seconds: int, now: datetime | None = None
    ) -> ClaimedInvestigation | None:
        """Take PENDING work, or RUNNING work whose lease expired, under a fresh token."""
        now = now or utc_now()
        token = str(uuid4())
        claimable = or_(
            InvestigationORM.lifecycle == PENDING,
            and_(
                InvestigationORM.lifecycle == RUNNING,
                InvestigationORM.lease_expires_at < now,
            ),
        )
        claimed = self._apply(
            investigation_id,
            claimable,
            lifecycle=RUNNING,
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            attempt_count=InvestigationORM.attempt_count + 1,
            error_message=None,
        )
        if claimed is None:
            return None
        orm = self.session.get(InvestigationORM, investigation_id)
        return ClaimedInvestigation(
            investigation=claimed,
            lease_token=token,
            attempt_count=orm.attempt_count,
            resume_payload=orm.pending_resume_payload,
        )

    def heartbeat(
        self,
        investigation_id: UUID,
        lease_token: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        now = now or utc_now()
        return (
            self._apply(
                investigation_id,
                InvestigationORM.lifecycle == RUNNING,
                InvestigationORM.lease_token == lease_token,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            is not None
        )

    def complete_investigation(
        self, investigation_id: UUID, report: InvestigationReport, *, lease_token: str
    ) -> Investigation | None:
        return self._apply(
            investigation_id,
            InvestigationORM.lifecycle == RUNNING,
            InvestigationORM.lease_token == lease_token,
            lifecycle=InvestigationLifecycle.COMPLETED,
            report_payload=report.model_dump(mode="json"),
            pending_human_review_payload=None,
            pending_resume_payload=None,
            error_message=None,
            lease_token=None,
            lease_expires_at=None,
        )

    def mark_awaiting_human_review(
        self,
        investigation_id: UUID,
        report: InvestigationReport | None,
        review: HumanReview,
        *,
        lease_token: str,
    ) -> Investigation | None:
        """Persist the report and review payload before the graph waits for an operator."""
        return self._apply(
            investigation_id,
            InvestigationORM.lifecycle == RUNNING,
            InvestigationORM.lease_token == lease_token,
            lifecycle=InvestigationLifecycle.AWAITING_HUMAN_REVIEW,
            report_payload=report.model_dump(mode="json") if report is not None else None,
            pending_human_review_payload=review.model_dump(mode="json"),
            error_message=None,
            lease_token=None,
            lease_expires_at=None,
        )

    def fail_investigation(
        self, investigation_id: UUID, error_message: str, *, lease_token: str
    ) -> Investigation | None:
        return self._apply(
            investigation_id,
            InvestigationORM.lifecycle == RUNNING,
            InvestigationORM.lease_token == lease_token,
            lifecycle=InvestigationLifecycle.FAILED,
            pending_human_review_payload=None,
            pending_resume_payload=None,
            error_message=error_message,
            lease_token=None,
            lease_expires_at=None,
        )

    def request_resume(
        self, investigation_id: UUID, resume_payload: dict
    ) -> Investigation | None:
        """Re-queue an investigation waiting on an operator; attempts restart at zero."""
        return self._apply(
            investigation_id,
            InvestigationORM.lifecycle == InvestigationLifecycle.AWAITING_HUMAN_REVIEW,
            lifecycle=PENDING,
            pending_resume_payload=resume_payload,
            pending_human_review_payload=None,
            attempt_count=0,
        )

    def stale_investigation_ids(
        self, *, pending_older_than_seconds: int, now: datetime | None = None
    ) -> list[UUID]:
        """PENDING rows idle too long (lost queue message) and RUNNING rows with dead leases."""
        now = now or utc_now()
        cutoff = now - timedelta(seconds=pending_older_than_seconds)
        statement = select(InvestigationORM.id).where(
            or_(
                and_(
                    InvestigationORM.lifecycle == PENDING,
                    InvestigationORM.updated_at < cutoff,
                ),
                and_(
                    InvestigationORM.lifecycle == RUNNING,
                    InvestigationORM.lease_expires_at < now,
                ),
            )
        )
        return list(self.session.scalars(statement).all())

    def count_by_lifecycle(self) -> dict[str, int]:
        statement = select(InvestigationORM.lifecycle, func.count()).group_by(
            InvestigationORM.lifecycle
        )
        return {lifecycle.value: count for lifecycle, count in self.session.execute(statement)}

import logging
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from incidentflow.agent.orchestration.policies.human_review import (
    HumanReviewEditError,
    jira_tool_resume_payload,
)
from incidentflow.application.jobs.queue import InMemoryJobQueue
from incidentflow.application.services.investigation_service import (
    InvestigationAlreadyActiveError,
    InvestigationService,
)
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewType,
)
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import InvestigationLifecycle, InvestigationStart
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM


class FailingQueue(InMemoryJobQueue):
    def send(self, investigation_id: UUID) -> None:
        raise RuntimeError("queue unavailable")


def create_incident(session: Session) -> IncidentORM:
    incident = IncidentORM(
        id=uuid4(),
        title="Payment API failures",
        description="Payment API has returned HTTP 500 errors since this morning.",
        priority=IncidentPriority.HIGH,
    )
    session.add(incident)
    session.commit()
    return incident


def make_service(session: Session, queue: InMemoryJobQueue) -> InvestigationService:
    return InvestigationService(
        InvestigationRepository(session), IncidentRepository(session), queue, object()
    )


def start_data(incident: IncidentORM) -> InvestigationStart:
    return InvestigationStart(
        incident_id=incident.id, incident_request="Investigate Payment API HTTP 500 errors."
    )


def force_awaiting(session: Session, investigation_id: UUID, review: HumanReview) -> None:
    orm = session.get(InvestigationORM, investigation_id)
    orm.lifecycle = InvestigationLifecycle.AWAITING_HUMAN_REVIEW
    orm.pending_human_review_payload = review.model_dump(mode="json")
    session.commit()
    session.expire_all()


def jira_review() -> HumanReview:
    return HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason="A Jira issue would communicate the confirmed impact.",
        evidence_references=["mongodb:event-17"],
        draft={
            "tool_name": "createJiraIssue",
            "tool_args": {"summary": "Payment API incident", "projectKey": "OPS"},
        },
    )


def test_start_returns_pending_and_enqueues_once() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        queue = InMemoryJobQueue()
        investigation = make_service(session, queue).start_investigation(start_data(incident))

        assert investigation is not None
        assert investigation.lifecycle == InvestigationLifecycle.PENDING
        assert queue.sent == [investigation.id]


def test_start_returns_none_for_unknown_incident() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        queue = InMemoryJobQueue()
        data = InvestigationStart(incident_id=uuid4(), incident_request="Investigate it.")

        assert make_service(session, queue).start_investigation(data) is None
        assert queue.sent == []


def test_start_rejects_active_investigation() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        queue = InMemoryJobQueue()
        service = make_service(session, queue)
        first = service.start_investigation(start_data(incident))

        with pytest.raises(InvestigationAlreadyActiveError) as error:
            service.start_investigation(start_data(incident))

        assert error.value.investigation_id == first.id
        assert queue.sent == [first.id]


def test_start_returns_pending_when_queue_send_fails(caplog) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        with caplog.at_level(logging.ERROR):
            investigation = make_service(session, FailingQueue()).start_investigation(
                start_data(incident)
            )

        assert investigation is not None
        assert investigation.lifecycle == InvestigationLifecycle.PENDING
        assert InvestigationRepository(session).get_investigation(investigation.id) is not None
        assert "queue" in caplog.text.lower()


def test_resume_stores_payload_and_enqueues_for_jira_write() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        queue = InMemoryJobQueue()
        service = make_service(session, queue)
        created = service.start_investigation(start_data(incident))
        review = jira_review()
        force_awaiting(session, created.id, review)
        decision = HumanReviewDecision(decision="APPROVE", actor="on-call-operator")

        resumed = service.request_human_review_resume(created.id, decision)

        assert resumed is not None
        assert resumed.lifecycle == InvestigationLifecycle.PENDING
        assert queue.sent == [created.id, created.id]
        payload = session.get(InvestigationORM, created.id).pending_resume_payload
        assert payload == {
            "command_resume": jira_tool_resume_payload(decision, review),
            "review_event": {
                "review": review.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
            "review_type": "JIRA_WRITE",
            "decision": "APPROVE",
        }


def test_resume_with_edited_draft_stores_approve_decision() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        service = make_service(session, InMemoryJobQueue())
        created = service.start_investigation(start_data(incident))
        force_awaiting(session, created.id, jira_review())
        decision = HumanReviewDecision(
            decision="APPROVE", actor="on-call-operator", edited_draft={"summary": "Edited"}
        )

        assert service.request_human_review_resume(created.id, decision) is not None

        payload = session.get(InvestigationORM, created.id).pending_resume_payload
        assert payload["decision"] == "APPROVE"
        assert payload["review_type"] == "JIRA_WRITE"


def test_resume_of_non_jira_review_uses_the_decision_as_resume_value() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        service = make_service(session, InMemoryJobQueue())
        created = service.start_investigation(start_data(incident))
        review = HumanReview(
            review_type=HumanReviewType.INSUFFICIENT_EVIDENCE, reason="Not enough evidence."
        )
        force_awaiting(session, created.id, review)
        decision = HumanReviewDecision(decision="REJECT", actor="on-call-operator")

        assert service.request_human_review_resume(created.id, decision) is not None

        payload = session.get(InvestigationORM, created.id).pending_resume_payload
        assert payload["command_resume"] == decision.model_dump(mode="json")
        assert payload["decision"] == "REJECT"
        assert payload["review_type"] == "INSUFFICIENT_EVIDENCE"


def test_second_resume_is_rejected() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        queue = InMemoryJobQueue()
        service = make_service(session, queue)
        created = service.start_investigation(start_data(incident))
        force_awaiting(session, created.id, jira_review())
        decision = HumanReviewDecision(decision="REJECT", actor="on-call-operator")

        assert service.request_human_review_resume(created.id, decision) is not None
        assert service.request_human_review_resume(created.id, decision) is None
        assert len(queue.sent) == 2


def test_resume_with_forbidden_edit_leaves_investigation_awaiting() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        queue = InMemoryJobQueue()
        service = make_service(session, queue)
        created = service.start_investigation(start_data(incident))
        force_awaiting(session, created.id, jira_review())
        decision = HumanReviewDecision(
            decision="APPROVE", actor="on-call-operator", edited_draft={"projectKey": "OTHER"}
        )

        with pytest.raises(HumanReviewEditError):
            service.request_human_review_resume(created.id, decision)

        current = InvestigationRepository(session).get_investigation(created.id)
        assert current.lifecycle == InvestigationLifecycle.AWAITING_HUMAN_REVIEW
        assert queue.sent == [created.id]


def test_concurrent_start_maps_integrity_error_to_already_active() -> None:
    class RacingRepository(InvestigationRepository):
        """The pre-check runs before another instance's insert commits."""

        def has_active_investigation(self, incident_id: UUID) -> bool:
            return False

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = create_incident(session)
        queue = InMemoryJobQueue()
        first = make_service(session, queue).start_investigation(start_data(incident))
        service = InvestigationService(
            RacingRepository(session), IncidentRepository(session), queue, object()
        )

        with pytest.raises(InvestigationAlreadyActiveError) as error:
            service.start_investigation(start_data(incident))

        assert error.value.investigation_id == first.id
        assert queue.sent == [first.id]

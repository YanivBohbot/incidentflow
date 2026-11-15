from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from incidentflow.agent.findings import InvestigationReport
from incidentflow.domain.human_review.models import HumanReview, HumanReviewType
from incidentflow.domain.incidents.models import IncidentPriority
from incidentflow.domain.investigations.models import (
    InvestigationCreate,
    InvestigationLifecycle,
    utc_now,
)
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM

PENDING = InvestigationLifecycle.PENDING
RUNNING = InvestigationLifecycle.RUNNING
COMPLETED = InvestigationLifecycle.COMPLETED
AWAITING = InvestigationLifecycle.AWAITING_HUMAN_REVIEW
REPORT = InvestigationReport(summary="Done.", confidence=0.8)
REVIEW = HumanReview(
    review_type=HumanReviewType.INSUFFICIENT_EVIDENCE,
    reason="Operator input needed.",
    evidence_references=[],
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture
def incident_id(session: Session) -> UUID:
    incident = IncidentORM(
        id=uuid4(), title="Payment API", description="HTTP 500s.", priority=IncidentPriority.HIGH
    )
    session.add(incident)
    session.commit()
    return incident.id


def _create(repo: InvestigationRepository, incident_id: UUID) -> UUID:
    return repo.create_investigation(
        InvestigationCreate(
            incident_id=incident_id, incident_request="Investigate.", incident_business_status="OPEN"
        )
    ).id


def test_claim_applies_once_and_fences_writes(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)

    first = repo.claim(inv_id, lease_seconds=300)
    assert first is not None
    assert first.attempt_count == 1 and first.investigation.lifecycle is RUNNING
    assert first.resume_payload is None
    assert repo.claim(inv_id, lease_seconds=300) is None
    assert repo.complete_investigation(inv_id, REPORT, lease_token="other") is None
    assert repo.get_investigation(inv_id).lifecycle is RUNNING
    completed = repo.complete_investigation(inv_id, REPORT, lease_token=first.lease_token)
    assert completed is not None and completed.lifecycle is COMPLETED
    assert repo.fail_investigation(inv_id, "late", lease_token=first.lease_token) is None


def test_claim_unknown_investigation_returns_none(session: Session) -> None:
    assert InvestigationRepository(session).claim(uuid4(), lease_seconds=300) is None


def test_expired_lease_is_reclaimed_and_stale_writer_ignored(
    session: Session, incident_id: UUID
) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    t0 = utc_now()

    first = repo.claim(inv_id, lease_seconds=300, now=t0)
    assert repo.claim(inv_id, lease_seconds=300, now=t0 + timedelta(seconds=299)) is None
    second = repo.claim(inv_id, lease_seconds=300, now=t0 + timedelta(seconds=301))

    assert first is not None and second is not None
    assert second.attempt_count == 2 and second.lease_token != first.lease_token
    assert repo.fail_investigation(inv_id, "late", lease_token=first.lease_token) is None
    assert repo.heartbeat(inv_id, first.lease_token, lease_seconds=300) is False
    assert repo.heartbeat(inv_id, second.lease_token, lease_seconds=300) is True
    failed = repo.fail_investigation(inv_id, "boom", lease_token=second.lease_token)
    assert failed is not None and failed.error_message == "boom"


def test_heartbeat_extends_the_lease(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    t0 = utc_now()
    claimed = repo.claim(inv_id, lease_seconds=60, now=t0)

    assert repo.heartbeat(
        inv_id, claimed.lease_token, lease_seconds=60, now=t0 + timedelta(seconds=50)
    )
    assert repo.claim(inv_id, lease_seconds=60, now=t0 + timedelta(seconds=70)) is None
    assert repo.claim(inv_id, lease_seconds=60, now=t0 + timedelta(seconds=111)) is not None


def test_request_resume_requeues_and_resets_attempts(
    session: Session, incident_id: UUID
) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    first = repo.claim(inv_id, lease_seconds=300)
    assert repo.request_resume(inv_id, {}) is None  # still RUNNING
    awaiting = repo.mark_awaiting_human_review(
        inv_id, REPORT, REVIEW, lease_token=first.lease_token
    )
    assert awaiting is not None and awaiting.lifecycle is AWAITING
    assert repo.heartbeat(inv_id, first.lease_token, lease_seconds=300) is False

    payload = {"command_resume": {"decisions": [{"type": "approve"}]}}
    queued = repo.request_resume(inv_id, payload)
    assert queued is not None and queued.lifecycle is PENDING
    assert repo.request_resume(inv_id, {}) is None

    claimed = repo.claim(inv_id, lease_seconds=300)
    assert claimed.attempt_count == 1
    assert claimed.resume_payload == payload

    repo.complete_investigation(inv_id, REPORT, lease_token=claimed.lease_token)
    session.expire_all()
    assert session.get(InvestigationORM, inv_id).pending_resume_payload is None


def test_has_active_investigation(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    assert repo.has_active_investigation(incident_id) is False
    inv_id = _create(repo, incident_id)
    assert repo.has_active_investigation(incident_id) is True
    claimed = repo.claim(inv_id, lease_seconds=300)
    assert repo.has_active_investigation(incident_id) is True
    repo.complete_investigation(inv_id, REPORT, lease_token=claimed.lease_token)
    assert repo.has_active_investigation(incident_id) is False


def test_stale_ids_cover_old_pending_and_expired_running(
    session: Session, incident_id: UUID
) -> None:
    repo = InvestigationRepository(session)
    now = utc_now()
    fresh = _create(repo, incident_id)
    old_pending = _create(repo, incident_id)
    expired = _create(repo, incident_id)
    live = _create(repo, incident_id)
    session.execute(
        update(InvestigationORM)
        .where(InvestigationORM.id == old_pending)
        .values(updated_at=now - timedelta(seconds=121))
    )
    session.commit()
    repo.claim(expired, lease_seconds=300, now=now - timedelta(seconds=400))
    repo.claim(live, lease_seconds=300, now=now)

    stale = repo.stale_investigation_ids(pending_older_than_seconds=120, now=now)

    assert set(stale) == {old_pending, expired}
    assert fresh not in stale and live not in stale


def test_count_by_lifecycle(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    assert repo.count_by_lifecycle() == {}
    _create(repo, incident_id)
    for _ in range(2):
        inv_id = _create(repo, incident_id)
        claimed = repo.claim(inv_id, lease_seconds=300)
        repo.complete_investigation(inv_id, REPORT, lease_token=claimed.lease_token)

    assert repo.count_by_lifecycle() == {"PENDING": 1, "COMPLETED": 2}

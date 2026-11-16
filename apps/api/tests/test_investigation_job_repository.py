from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.exc import IntegrityError
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
    is_active_investigation_conflict,
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


def _new_incident(session: Session) -> UUID:
    incident = IncidentORM(
        id=uuid4(), title="Payment API", description="HTTP 500s.", priority=IncidentPriority.HIGH
    )
    session.add(incident)
    session.commit()
    return incident.id


@pytest.fixture
def incident_id(session: Session) -> UUID:
    return _new_incident(session)


def _create(repo: InvestigationRepository, incident_id: UUID) -> UUID:
    return repo.create_investigation(
        InvestigationCreate(
            incident_id=incident_id,
            incident_request="Investigate.",
            incident_business_status="OPEN",
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


def test_request_resume_requeues_and_resets_attempts(session: Session, incident_id: UUID) -> None:
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


def test_pending_review_counts_as_active(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    claimed = repo.claim(inv_id, lease_seconds=300)
    repo.mark_awaiting_human_review(inv_id, REPORT, REVIEW, lease_token=claimed.lease_token)

    assert repo.has_active_investigation(incident_id) is True


def test_resume_into_an_active_incident_rolls_back(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    paused = _create(repo, incident_id)
    claimed = repo.claim(paused, lease_seconds=300)
    repo.mark_awaiting_human_review(paused, REPORT, REVIEW, lease_token=claimed.lease_token)
    _create(repo, incident_id)  # legacy state: a second row started during the review

    with pytest.raises(IntegrityError) as error:
        repo.request_resume(paused, {"command_resume": {}})

    assert is_active_investigation_conflict(error.value)
    session.expire_all()
    row = session.get(InvestigationORM, paused)
    assert row.lifecycle is AWAITING and row.pending_resume_payload is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            'duplicate key value violates unique constraint "uq_investigations_active_incident"',
            True,
        ),
        ("UNIQUE constraint failed: investigations.incident_id", True),
        ("UNIQUE constraint failed: investigations.workflow_thread_id", False),
        ('duplicate key value violates unique constraint "investigations_pkey"', False),
    ],
)
def test_is_active_investigation_conflict_matches_only_the_active_index(
    message: str, expected: bool
) -> None:
    error = IntegrityError("INSERT ...", {}, Exception(message))

    assert is_active_investigation_conflict(error) is expected


def test_stale_ids_cover_old_pending_and_expired_running(session: Session) -> None:
    repo = InvestigationRepository(session)
    now = utc_now()
    # One incident each: an incident holds at most one active investigation.
    fresh, old_pending, expired, live = (_create(repo, _new_incident(session)) for _ in range(4))
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
    for _ in range(2):
        inv_id = _create(repo, incident_id)
        claimed = repo.claim(inv_id, lease_seconds=300)
        repo.complete_investigation(inv_id, REPORT, lease_token=claimed.lease_token)
    _create(repo, incident_id)

    assert repo.count_by_lifecycle() == {"PENDING": 1, "COMPLETED": 2}


def test_running_row_with_null_lease_is_claimable_and_stale(
    session: Session, incident_id: UUID
) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    session.execute(
        update(InvestigationORM)
        .where(InvestigationORM.id == inv_id)
        .values(lifecycle=RUNNING, lease_token=None, lease_expires_at=None)
    )
    session.commit()

    assert repo.stale_investigation_ids(pending_older_than_seconds=120) == [inv_id]
    claimed = repo.claim(inv_id, lease_seconds=300)
    assert claimed is not None and claimed.attempt_count == 1


def test_mark_awaiting_human_review_clears_the_resume_payload(
    session: Session, incident_id: UUID
) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    first = repo.claim(inv_id, lease_seconds=300)
    repo.mark_awaiting_human_review(inv_id, REPORT, REVIEW, lease_token=first.lease_token)
    repo.request_resume(inv_id, {"command_resume": {"decisions": [{"type": "reject"}]}})
    resumed = repo.claim(inv_id, lease_seconds=300)

    paused = repo.mark_awaiting_human_review(
        inv_id, REPORT, REVIEW, lease_token=resumed.lease_token
    )

    assert paused is not None
    session.expire_all()
    assert session.get(InvestigationORM, inv_id).pending_resume_payload is None


def test_second_active_investigation_violates_unique_index(
    session: Session, incident_id: UUID
) -> None:
    repo = InvestigationRepository(session)
    _create(repo, incident_id)

    with pytest.raises(IntegrityError):
        _create(repo, incident_id)

    session.rollback()
    assert len(repo.list_for_incident(incident_id)) == 1


def test_completed_investigation_allows_a_new_one(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    first = _create(repo, incident_id)
    claimed = repo.claim(first, lease_seconds=300)
    repo.complete_investigation(first, REPORT, lease_token=claimed.lease_token)

    second = _create(repo, incident_id)

    assert second != first
    assert repo.get_investigation(second).lifecycle is PENDING


def test_claim_uses_database_time_when_now_omitted(session: Session, incident_id: UUID) -> None:
    repo = InvestigationRepository(session)
    inv_id = _create(repo, incident_id)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    before = datetime.now(UTC)
    try:
        assert repo.claim(inv_id, lease_seconds=300) is not None
    finally:
        event.remove(engine, "before_cursor_execute", record)

    # The lease is computed from the shared database clock, not this process's clock.
    assert any("CURRENT_TIMESTAMP" in statement for statement in statements)
    session.expire_all()
    expires_at = session.get(InvestigationORM, inv_id).lease_expires_at.replace(tzinfo=UTC)
    # SQLite's CURRENT_TIMESTAMP has one-second precision.
    assert before + timedelta(seconds=298) <= expires_at <= before + timedelta(seconds=302)

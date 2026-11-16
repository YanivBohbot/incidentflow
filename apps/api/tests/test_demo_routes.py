import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incidentflow.api.routes.demo import get_demo_service
from incidentflow.api.routes.demo import router as demo_router
from incidentflow.application.services.demo_service import (
    DemoService,
    LambdaDemoRunner,
    LocalDemoRunner,
)
from incidentflow.core.auth import LOCAL_PRINCIPAL, Principal, get_principal
from incidentflow.core.config import Settings, get_settings
from incidentflow.demo.scenarios import DEMO_ALARM_NAMES, SCENARIOS
from incidentflow.domain.incidents.models import (
    AlarmIncidentCreate,
    IncidentCreate,
    IncidentPriority,
    IncidentStatus,
)
from incidentflow.domain.investigations.models import InvestigationCreate, InvestigationLifecycle
from incidentflow.infrastructure.database.base import Base
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.models import IncidentORM, InvestigationORM

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
COOLDOWN = 600


class FakeRunner:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def start(self, run_id: str) -> None:
        self.run_ids.append(run_id)


def alarm_data(name: str = "if-checkout") -> AlarmIncidentCreate:
    return AlarmIncidentCreate(
        title="Checkout alarm in ALARM",
        description="Checkout API error rate crossed the alarm threshold.",
        priority=IncidentPriority.HIGH,
        service="checkout-api",
        external_id=f"arn:aws:cloudwatch:us-east-1:123456789012:alarm:{name}",
    )


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def repository(session: Session) -> IncidentRepository:
    return IncidentRepository(session)


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def build_client(
    repository: IncidentRepository,
    runner: FakeRunner,
    principal: Principal = LOCAL_PRINCIPAL,
) -> TestClient:
    app = FastAPI()
    app.include_router(demo_router, prefix="/api")
    app.dependency_overrides[get_demo_service] = lambda: DemoService(
        repository,
        runner,
        COOLDOWN,
        lambda: NOW,
        investigations=InvestigationRepository(repository.session),
    )
    app.dependency_overrides[get_principal] = lambda: principal
    return TestClient(app)


@pytest.fixture
def enable_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ENABLED", "true")
    get_settings.cache_clear()


@pytest.fixture
def client(repository: IncidentRepository, fake_runner: FakeRunner) -> TestClient:
    return build_client(repository, fake_runner)


@pytest.fixture
def operator_client(client: TestClient) -> TestClient:
    return client


@pytest.fixture
def viewer_client(repository: IncidentRepository, fake_runner: FakeRunner) -> TestClient:
    return build_client(repository, fake_runner, Principal("bob", frozenset({"viewer"})))


def set_created_at(session: Session, incident_id: Any, created_at: datetime) -> None:
    orm = session.get(IncidentORM, incident_id)
    orm.created_at = created_at
    session.commit()


def test_demo_status_reports_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/demo")

    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_demo_status_reports_enabled(client: TestClient, enable_demo: None) -> None:
    assert client.get("/api/demo").json() == {"enabled": True}


def test_run_demo_is_404_when_disabled(operator_client: TestClient, fake_runner) -> None:
    response = operator_client.post("/api/demo/runs")

    assert response.status_code == 404
    assert response.json() == {"detail": "Demo is disabled"}
    assert fake_runner.run_ids == []


def test_run_demo_requires_operator(viewer_client: TestClient, enable_demo, fake_runner) -> None:
    response = viewer_client.post("/api/demo/runs")

    assert response.status_code == 403
    assert fake_runner.run_ids == []
    assert viewer_client.get("/api/demo").status_code == 200


def test_run_demo_closes_previous_demo_incidents_and_starts_runner(
    operator_client: TestClient, enable_demo, fake_runner, repository: IncidentRepository
) -> None:
    previous = repository.create_alarm_incident(alarm_data("if-checkout"))
    manual = repository.create_incident(
        IncidentCreate(title="Manual incident", description="An operator reported it by hand.")
    )

    response = operator_client.post("/api/demo/runs")

    assert response.status_code == 202
    body = response.json()
    assert body["started"] is True
    assert body["closed_incidents"] == 1
    assert fake_runner.run_ids == [body["run_id"]]
    assert repository.get_incident(previous.id).status is IncidentStatus.CLOSED
    assert repository.get_incident(manual.id).status is IncidentStatus.OPEN


def test_second_run_closes_nothing_new(
    operator_client: TestClient, enable_demo, fake_runner, repository: IncidentRepository
) -> None:
    repository.create_alarm_incident(alarm_data("if-checkout"))

    first = operator_client.post("/api/demo/runs").json()
    second = operator_client.post("/api/demo/runs").json()

    assert first["closed_incidents"] == 1
    assert second["closed_incidents"] == 0
    assert len(fake_runner.run_ids) == 2
    assert first["run_id"] != second["run_id"]


def test_auto_start_skips_when_a_demo_incident_is_recent(
    operator_client: TestClient,
    enable_demo,
    fake_runner,
    repository: IncidentRepository,
    session: Session,
) -> None:
    incident = repository.create_alarm_incident(alarm_data("if-checkout"))
    set_created_at(session, incident.id, NOW - timedelta(minutes=5))

    response = operator_client.post("/api/demo/runs", params={"only_if_idle": "true"})

    assert response.status_code == 200
    assert response.json()["started"] is False
    assert response.json()["run_id"] is None
    assert response.json()["closed_incidents"] == 0
    assert fake_runner.run_ids == []
    assert repository.get_incident(incident.id).status is IncidentStatus.OPEN


def test_auto_start_runs_when_demo_is_idle(
    operator_client: TestClient,
    enable_demo,
    fake_runner,
    repository: IncidentRepository,
    session: Session,
) -> None:
    incident = repository.create_alarm_incident(alarm_data("if-checkout"))
    set_created_at(session, incident.id, NOW - timedelta(minutes=11))

    response = operator_client.post("/api/demo/runs", params={"only_if_idle": "true"})

    assert response.status_code == 202
    assert response.json()["started"] is True
    assert len(fake_runner.run_ids) == 1


def _investigate(session: Session, incident_id: Any, lifecycle: InvestigationLifecycle) -> None:
    investigation = InvestigationRepository(session).create_investigation(
        InvestigationCreate(
            incident_id=incident_id,
            incident_request="Investigate.",
            incident_business_status="OPEN",
        )
    )
    orm = session.get(InvestigationORM, investigation.id)
    orm.lifecycle = lifecycle
    session.commit()


@pytest.mark.parametrize(
    "lifecycle",
    [
        InvestigationLifecycle.PENDING,
        InvestigationLifecycle.RUNNING,
        InvestigationLifecycle.AWAITING_HUMAN_REVIEW,
    ],
)
def test_auto_start_skips_when_a_demo_incident_is_under_investigation(
    operator_client: TestClient,
    enable_demo,
    fake_runner,
    repository: IncidentRepository,
    session: Session,
    lifecycle: InvestigationLifecycle,
) -> None:
    incident = repository.create_alarm_incident(alarm_data("if-checkout"))
    set_created_at(session, incident.id, NOW - timedelta(minutes=30))
    _investigate(session, incident.id, lifecycle)

    response = operator_client.post("/api/demo/runs", params={"only_if_idle": "true"})

    assert response.status_code == 200
    assert response.json()["started"] is False
    assert response.json()["closed_incidents"] == 0
    assert fake_runner.run_ids == []
    assert repository.get_incident(incident.id).status is IncidentStatus.OPEN


def test_auto_start_runs_when_the_investigation_is_completed(
    operator_client: TestClient,
    enable_demo,
    fake_runner,
    repository: IncidentRepository,
    session: Session,
) -> None:
    incident = repository.create_alarm_incident(alarm_data("if-checkout"))
    set_created_at(session, incident.id, NOW - timedelta(minutes=30))
    _investigate(session, incident.id, InvestigationLifecycle.COMPLETED)

    response = operator_client.post("/api/demo/runs", params={"only_if_idle": "true"})

    assert response.status_code == 202
    assert len(fake_runner.run_ids) == 1


def test_manual_run_still_closes_incidents_under_investigation(
    operator_client: TestClient,
    enable_demo,
    fake_runner,
    repository: IncidentRepository,
    session: Session,
) -> None:
    incident = repository.create_alarm_incident(alarm_data("if-checkout"))
    _investigate(session, incident.id, InvestigationLifecycle.RUNNING)

    response = operator_client.post("/api/demo/runs")

    assert response.status_code == 202
    assert response.json()["closed_incidents"] == 1


def test_auto_start_runs_when_there_are_no_demo_incidents(
    operator_client: TestClient, enable_demo, fake_runner
) -> None:
    response = operator_client.post("/api/demo/runs?only_if_idle=true")

    assert response.status_code == 202
    assert len(fake_runner.run_ids) == 1


def test_manual_run_ignores_the_cooldown(
    operator_client: TestClient,
    enable_demo,
    fake_runner,
    repository: IncidentRepository,
    session: Session,
) -> None:
    incident = repository.create_alarm_incident(alarm_data("if-checkout"))
    set_created_at(session, incident.id, NOW - timedelta(minutes=1))

    response = operator_client.post("/api/demo/runs")

    assert response.status_code == 202
    assert len(fake_runner.run_ids) == 1


def test_lambda_runner_invokes_asynchronously() -> None:
    client = boto3.client(
        "lambda",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with Stubber(client) as stubber:
        stubber.add_response(
            "invoke",
            {"StatusCode": 202},
            {
                "FunctionName": "incidentflow-demo",
                "InvocationType": "Event",
                "Payload": json.dumps({"run_id": "run-1"}),
            },
        )

        LambdaDemoRunner(client, "incidentflow-demo").start("run-1")

        stubber.assert_no_pending_responses()


class FakeAwsSession:
    region_name = "eu-west-1"

    def client(self, name: str) -> Any:
        assert name == "sts"
        return SimpleNamespace(get_caller_identity=lambda: {"Account": "123456789012"})


def local_runner(
    session_factory: sessionmaker[Session],
    simulator_factory: Callable[..., Any],
    background: BackgroundTasks | None = None,
) -> LocalDemoRunner:
    settings = Settings(openai_api_key="x", database_url="sqlite://")
    return LocalDemoRunner(
        settings,
        session_factory,
        background or BackgroundTasks(),
        aws_session_factory=lambda _settings: FakeAwsSession(),
        simulator_factory=simulator_factory,
    )


def test_local_runner_ingests_each_fired_alarm(session_factory: sessionmaker[Session]) -> None:
    runs: list[str] = []

    def simulator_factory(_aws_session: Any, on_alarm_fired: Callable[..., None]) -> Any:
        def run(run_id: str) -> None:
            runs.append(run_id)
            on_alarm_fired(SCENARIOS[0], run_id)
            on_alarm_fired(SCENARIOS[1], run_id)

        return SimpleNamespace(run=run)

    local_runner(session_factory, simulator_factory).run("run-1")

    assert runs == ["run-1"]
    with session_factory() as session:
        incidents = session.query(IncidentORM).order_by(IncidentORM.created_at).all()
    assert len(incidents) == 2
    first = incidents[0]
    assert first.title == SCENARIOS[0].title
    assert first.priority is SCENARIOS[0].priority
    assert first.service == SCENARIOS[0].service
    assert first.external_id == (
        f"arn:aws:cloudwatch:eu-west-1:123456789012:alarm:{SCENARIOS[0].alarm_name}"
    )


def test_local_runner_start_schedules_a_background_task(
    session_factory: sessionmaker[Session],
) -> None:
    background = BackgroundTasks()

    local_runner(session_factory, lambda *_: None, background).start("run-1")

    assert len(background.tasks) == 1


def test_demo_service_closes_every_demo_alarm_name(
    repository: IncidentRepository, fake_runner: FakeRunner
) -> None:
    for name in DEMO_ALARM_NAMES:
        repository.create_alarm_incident(alarm_data(name))

    result = DemoService(repository, fake_runner, COOLDOWN, lambda: NOW).start_run()

    assert result.closed_incidents == len(DEMO_ALARM_NAMES)


def test_local_runner_skips_a_run_while_another_is_in_progress(
    session_factory: sessionmaker[Session],
) -> None:
    import threading

    entered, release = threading.Event(), threading.Event()
    runs: list[str] = []

    def simulator_factory(_aws_session: Any, _fired: Callable[..., None]) -> Any:
        def run(run_id: str) -> None:
            runs.append(run_id)
            entered.set()
            release.wait(timeout=5)

        return SimpleNamespace(run=run)

    first = threading.Thread(
        target=local_runner(session_factory, simulator_factory).run, args=("run-1",)
    )
    first.start()
    assert entered.wait(timeout=5)
    try:
        local_runner(session_factory, simulator_factory).run("run-2")
    finally:
        release.set()
        first.join(timeout=5)

    assert runs == ["run-1"]
    local_runner(session_factory, simulator_factory).run("run-3")
    assert runs == ["run-1", "run-3"]

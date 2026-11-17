"""Demo endpoints: replay outages through real CloudWatch alarms."""

from typing import Annotated

import boto3
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from incidentflow.api.routes.incidents import CAN_OPERATE, CAN_READ, get_db_session
from incidentflow.application.services.demo_service import (
    DemoRunner,
    DemoService,
    LambdaDemoRunner,
    LocalDemoRunner,
)
from incidentflow.core.auth import OperatorPrincipal
from incidentflow.core.config import get_settings
from incidentflow.domain.demo.models import DemoRunStarted, DemoStatus
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.session import SessionLocal

RUN_IN_PROGRESS_INTERVALS = 3


def get_demo_runner(background: BackgroundTasks) -> DemoRunner:
    """Run the demo in the Lambda when one is configured, otherwise in this process."""
    settings = get_settings()
    if settings.demo_function_name:
        return LambdaDemoRunner(boto3.client("lambda"), settings.demo_function_name)
    return LocalDemoRunner(settings, SessionLocal, background)


def get_demo_service(
    session: Annotated[Session, Depends(get_db_session)],
    runner: Annotated[DemoRunner, Depends(get_demo_runner)],
) -> DemoService:
    """Build the demo service; a run counts as in progress for three alarm intervals."""
    settings = get_settings()
    return DemoService(
        IncidentRepository(session),
        runner,
        settings.demo_auto_cooldown_seconds,
        investigations=InvestigationRepository(session),
        run_in_progress_seconds=settings.demo_interval_seconds * RUN_IN_PROGRESS_INTERVALS,
        events=IncidentEventRepository(session),
    )


DemoServiceDep = Annotated[DemoService, Depends(get_demo_service)]

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.get("", response_model=DemoStatus, dependencies=CAN_READ)
def demo_status() -> DemoStatus:
    """Tell the dashboard whether the demo is enabled."""
    return DemoStatus(enabled=get_settings().demo_enabled)


@router.post(
    "/runs",
    response_model=DemoRunStarted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=CAN_OPERATE,
)
def start_demo_run(
    service: DemoServiceDep,
    response: Response,
    principal: OperatorPrincipal,
    only_if_idle: bool = False,
) -> DemoRunStarted:
    """Start a demo run, or answer 200 without starting when one is not allowed."""
    if not get_settings().demo_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo is disabled")
    actor = "demo" if only_if_idle else principal.username
    result = service.start_run(only_if_idle=only_if_idle, actor=actor)
    if not result.started:
        response.status_code = status.HTTP_200_OK
    return result

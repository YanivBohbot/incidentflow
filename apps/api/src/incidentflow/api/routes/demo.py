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
from incidentflow.core.config import get_settings
from incidentflow.domain.demo.models import DemoRunStarted, DemoStatus
from incidentflow.infrastructure.database.incident_repository import IncidentRepository
from incidentflow.infrastructure.database.investigation_repository import (
    InvestigationRepository,
)
from incidentflow.infrastructure.database.session import SessionLocal


def get_demo_runner(background: BackgroundTasks) -> DemoRunner:
    settings = get_settings()
    if settings.demo_function_name:
        return LambdaDemoRunner(boto3.client("lambda"), settings.demo_function_name)
    return LocalDemoRunner(settings, SessionLocal, background)


def get_demo_service(
    session: Annotated[Session, Depends(get_db_session)],
    runner: Annotated[DemoRunner, Depends(get_demo_runner)],
) -> DemoService:
    return DemoService(
        IncidentRepository(session),
        runner,
        get_settings().demo_auto_cooldown_seconds,
        investigations=InvestigationRepository(session),
    )


DemoServiceDep = Annotated[DemoService, Depends(get_demo_service)]

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.get("", response_model=DemoStatus, dependencies=CAN_READ)
def demo_status() -> DemoStatus:
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
    only_if_idle: bool = False,
) -> DemoRunStarted:
    if not get_settings().demo_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo is disabled")
    result = service.start_run(only_if_idle=only_if_idle)
    if not result.started:
        response.status_code = status.HTTP_200_OK
    return result

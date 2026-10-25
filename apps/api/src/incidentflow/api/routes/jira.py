from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from incidentflow.api.routes.investigations import get_investigation_service
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.application.services.jira_ticket_service import (
    JiraMCPNotEnabledError,
    JiraTicketService,
)
from incidentflow.core.config import get_settings
from incidentflow.domain.jira.models import (
    JiraIssueCommentRequest,
    JiraIssueCreateRequest,
    JiraMCPResult,
)


def get_jira_ticket_service() -> JiraTicketService:
    return JiraTicketService(get_settings())


InvestigationServiceDep = Annotated[InvestigationService, Depends(get_investigation_service)]
JiraTicketServiceDep = Annotated[JiraTicketService, Depends(get_jira_ticket_service)]

router = APIRouter(prefix="/jira", tags=["Jira"])


def _jira_unavailable(error: JiraMCPNotEnabledError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))


@router.get("/resources", response_model=JiraMCPResult)
async def list_resources(service: JiraTicketServiceDep) -> JiraMCPResult:
    try:
        return await service.get_resources()
    except JiraMCPNotEnabledError as error:
        raise _jira_unavailable(error) from error


@router.get("/projects", response_model=JiraMCPResult)
async def list_projects(cloud_id: str, service: JiraTicketServiceDep) -> JiraMCPResult:
    try:
        return await service.get_projects(cloud_id)
    except JiraMCPNotEnabledError as error:
        raise _jira_unavailable(error) from error


@router.get("/projects/{project_key}/issue-types", response_model=JiraMCPResult)
async def list_issue_types(
    project_key: str, cloud_id: str, service: JiraTicketServiceDep
) -> JiraMCPResult:
    try:
        return await service.get_issue_types(cloud_id, project_key)
    except JiraMCPNotEnabledError as error:
        raise _jira_unavailable(error) from error


@router.post(
    "/investigations/{investigation_id}/issues",
    response_model=JiraMCPResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_issue(
    investigation_id: UUID,
    data: JiraIssueCreateRequest,
    investigation_service: InvestigationServiceDep,
    jira_service: JiraTicketServiceDep,
) -> JiraMCPResult:
    if investigation_service.get_investigation(investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    try:
        return await jira_service.create_issue(data)
    except JiraMCPNotEnabledError as error:
        raise _jira_unavailable(error) from error


@router.post("/issues/comments", response_model=JiraMCPResult, status_code=status.HTTP_201_CREATED)
async def add_comment(
    data: JiraIssueCommentRequest, service: JiraTicketServiceDep
) -> JiraMCPResult:
    try:
        return await service.add_comment(data)
    except JiraMCPNotEnabledError as error:
        raise _jira_unavailable(error) from error

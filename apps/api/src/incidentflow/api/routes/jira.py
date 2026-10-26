from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from incidentflow.api.routes.investigations import (
    get_db_session,
    get_investigation_service,
)
from incidentflow.application.services.investigation_service import InvestigationService
from incidentflow.application.services.jira_approval_service import (
    JiraApprovalService,
    JiraProposalNotApprovableError,
    JiraProposalNotFoundError,
)
from incidentflow.application.services.jira_ticket_service import (
    JiraMCPNotEnabledError,
    JiraTicketService,
)
from incidentflow.core.config import get_settings
from incidentflow.domain.jira.models import (
    JiraActionProposal,
    JiraIssueCommentRequest,
    JiraIssueCreateRequest,
    JiraMCPResult,
)
from incidentflow.infrastructure.database.jira_proposal_repository import JiraProposalRepository


def get_jira_ticket_service() -> JiraTicketService:
    return JiraTicketService(get_settings())


def get_jira_proposal_service(
    session: Annotated[Session, Depends(get_db_session)],
    ticket_service: Annotated[JiraTicketService, Depends(get_jira_ticket_service)],
) -> JiraApprovalService:
    return JiraApprovalService(JiraProposalRepository(session), ticket_service)


InvestigationServiceDep = Annotated[InvestigationService, Depends(get_investigation_service)]
JiraTicketServiceDep = Annotated[JiraTicketService, Depends(get_jira_ticket_service)]
JiraApprovalServiceDep = Annotated[JiraApprovalService, Depends(get_jira_proposal_service)]

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
    response_model=JiraActionProposal,
    status_code=status.HTTP_201_CREATED,
)
async def propose_issue(
    investigation_id: UUID,
    data: JiraIssueCreateRequest,
    investigation_service: InvestigationServiceDep,
    approval_service: JiraApprovalServiceDep,
) -> JiraActionProposal:
    if investigation_service.get_investigation(investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return approval_service.propose_issue(investigation_id, data)


@router.post(
    "/investigations/{investigation_id}/comments",
    response_model=JiraActionProposal,
    status_code=status.HTTP_201_CREATED,
)
async def propose_comment(
    investigation_id: UUID,
    data: JiraIssueCommentRequest,
    investigation_service: InvestigationServiceDep,
    approval_service: JiraApprovalServiceDep,
) -> JiraActionProposal:
    if investigation_service.get_investigation(investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return approval_service.propose_comment(investigation_id, data)


@router.get(
    "/investigations/{investigation_id}/proposals", response_model=list[JiraActionProposal]
)
def list_proposals(
    investigation_id: UUID,
    investigation_service: InvestigationServiceDep,
    approval_service: JiraApprovalServiceDep,
) -> list[JiraActionProposal]:
    if investigation_service.get_investigation(investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return approval_service.list_proposals(investigation_id)


@router.post("/proposals/{proposal_id}/approve", response_model=JiraActionProposal)
async def approve_proposal(
    proposal_id: UUID, approval_service: JiraApprovalServiceDep
) -> JiraActionProposal:
    try:
        return await approval_service.approve_and_execute(proposal_id)
    except JiraProposalNotFoundError as error:
        raise HTTPException(status_code=404, detail="Jira proposal not found") from error
    except JiraProposalNotApprovableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

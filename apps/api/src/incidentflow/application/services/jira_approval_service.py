"""Server-side human-in-the-loop gate for Jira mutations."""

from uuid import UUID

from incidentflow.application.services.jira_ticket_service import JiraTicketService
from incidentflow.domain.jira.models import (
    JiraActionProposal,
    JiraIssueCommentRequest,
    JiraIssueCreateRequest,
    JiraProposalAction,
)
from incidentflow.infrastructure.database.jira_proposal_repository import JiraProposalRepository


class JiraProposalNotFoundError(LookupError):
    """Raised when a requested approval does not exist."""


class JiraProposalNotApprovableError(RuntimeError):
    """Raised when a proposal has already left the pending state."""


class JiraApprovalService:
    def __init__(
        self,
        repository: JiraProposalRepository,
        jira_ticket_service: JiraTicketService,
    ) -> None:
        self.repository = repository
        self.jira_ticket_service = jira_ticket_service

    def propose_issue(
        self, investigation_id: UUID, request: JiraIssueCreateRequest
    ) -> JiraActionProposal:
        return self.repository.create(
            investigation_id,
            JiraProposalAction.CREATE_ISSUE,
            request.tool_arguments(),
        )

    def propose_comment(
        self, investigation_id: UUID, request: JiraIssueCommentRequest
    ) -> JiraActionProposal:
        return self.repository.create(
            investigation_id,
            JiraProposalAction.ADD_COMMENT,
            request.tool_arguments(),
        )

    def get_proposal(self, proposal_id: UUID) -> JiraActionProposal | None:
        return self.repository.get(proposal_id)

    def list_proposals(self, investigation_id: UUID) -> list[JiraActionProposal]:
        return self.repository.list_for_investigation(investigation_id)

    async def approve_and_execute(
        self, proposal_id: UUID, *, approved_by: str = "unattributed"
    ) -> JiraActionProposal:
        proposal = self.repository.get(proposal_id)
        if proposal is None:
            raise JiraProposalNotFoundError

        claimed = self.repository.claim_for_execution(proposal_id, approved_by)
        if claimed is None:
            raise JiraProposalNotApprovableError(
                "This Jira proposal is no longer pending and cannot be executed again."
            )

        try:
            if claimed.action is JiraProposalAction.CREATE_ISSUE:
                result = await self.jira_ticket_service.create_issue(
                    JiraIssueCreateRequest.model_validate(claimed.payload)
                )
            else:
                result = await self.jira_ticket_service.add_comment(
                    JiraIssueCommentRequest.model_validate(claimed.payload)
                )
        except Exception as error:
            failed = self.repository.mark_failed(proposal_id, str(error))
            if failed is None:
                raise RuntimeError("Jira proposal disappeared during execution.") from error
            return failed

        completed = self.repository.mark_executed(
            proposal_id,
            {"operation": result.operation, "result": result.result},
        )
        if completed is None:
            raise RuntimeError("Jira proposal disappeared after execution.")
        return completed

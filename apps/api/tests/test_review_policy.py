import pytest

from incidentflow.agent.findings import InvestigationReport
from incidentflow.agent.orchestration.policies.human_review import (
    HumanReviewEditError,
    accepted_human_review,
    jira_tool_resume_payload,
    jira_write_review_from_interrupt,
)
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewType,
)


def test_jira_recommendation_does_not_duplicate_tool_level_approval() -> None:
    report = InvestigationReport(
        summary="A Jira incident should be created.",
        confidence=0.8,
        human_review=HumanReview(
            review_type=HumanReviewType.JIRA_WRITE,
            reason="Escalate the confirmed production impact.",
            evidence_references=["mongodb:event-17"],
            draft={"summary": "Payment API incident"},
        ),
    )

    assert accepted_human_review(report) is None


def test_non_jira_report_review_remains_eligible_for_workflow_pause() -> None:
    report = InvestigationReport(
        summary="More evidence is required before a recommendation.",
        confidence=0.8,
        human_review=HumanReview(
            review_type=HumanReviewType.INSUFFICIENT_EVIDENCE,
            reason="The incident lacks a reliable deployment correlation.",
        ),
    )

    assert accepted_human_review(report) is report.human_review


def test_jira_tool_interrupt_becomes_a_persistable_review_and_resume_payload() -> None:
    review = jira_write_review_from_interrupt(
        {
            "action_requests": [
                {
                    "name": "createJiraIssue",
                    "arguments": {"summary": "Payment API incident"},
                    "description": "Jira issue creation requires operator approval.",
                }
            ]
        }
    )

    assert review is not None
    assert review.review_type is HumanReviewType.JIRA_WRITE
    assert review.draft["tool_name"] == "createJiraIssue"

    payload = jira_tool_resume_payload(
        HumanReviewDecision(decision="APPROVE", actor="on-call-operator")
    )

    assert payload == {"decisions": [{"type": "approve"}]}


def _jira_issue_review() -> HumanReview:
    review = jira_write_review_from_interrupt(
        {
            "action_requests": [
                {
                    "name": "createJiraIssue",
                    "args": {
                        "cloudId": "cloud-1",
                        "projectKey": "SAM1",
                        "issueType": "Bug",
                        "summary": "Payment API incident",
                        "description": "HTTP 500 after deploy.",
                    },
                }
            ]
        }
    )
    assert review is not None
    return review


def test_jira_review_lists_only_text_fields_as_editable() -> None:
    assert _jira_issue_review().draft["editable_fields"] == ["summary", "description"]


def test_approved_edit_replaces_only_permitted_text_and_keeps_the_target() -> None:
    payload = jira_tool_resume_payload(
        HumanReviewDecision(
            decision="APPROVE",
            actor="on-call-operator",
            edited_draft={"summary": "Payment API HTTP 500 after deploy 184"},
        ),
        _jira_issue_review(),
    )

    assert payload == {
        "decisions": [
            {
                "type": "edit",
                "edited_action": {
                    "name": "createJiraIssue",
                    "args": {
                        "cloudId": "cloud-1",
                        "projectKey": "SAM1",
                        "issueType": "Bug",
                        "summary": "Payment API HTTP 500 after deploy 184",
                        "description": "HTTP 500 after deploy.",
                    },
                },
            }
        ]
    }


def test_editing_the_jira_target_is_refused() -> None:
    with pytest.raises(HumanReviewEditError, match="projectKey"):
        jira_tool_resume_payload(
            HumanReviewDecision(
                decision="APPROVE", actor="on-call-operator", edited_draft={"projectKey": "PROD"}
            ),
            _jira_issue_review(),
        )


def test_request_information_resumes_the_jira_agent_as_a_rejection_with_the_question() -> None:
    payload = jira_tool_resume_payload(
        HumanReviewDecision(
            decision="REQUEST_INFORMATION",
            actor="on-call-operator",
            reason="Which deploy introduced the regression?",
        ),
        _jira_issue_review(),
    )

    assert payload == {
        "decisions": [{"type": "reject", "message": "Which deploy introduced the regression?"}]
    }

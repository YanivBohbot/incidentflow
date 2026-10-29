from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.agent.orchestration.review_policy import accepted_human_review
from incidentflow.domain.human_review.models import HumanReview, HumanReviewType


def test_supported_jira_recommendation_with_evidence_becomes_a_review_request() -> None:
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

    request = accepted_human_review(report)

    assert request is not None
    assert request.review_type is HumanReviewType.JIRA_WRITE
    assert request.evidence_references == ["mongodb:event-17"]


def test_jira_recommendation_without_evidence_is_not_eligible_for_review() -> None:
    report = InvestigationReport(
        summary="A Jira incident should be created.",
        confidence=0.8,
        human_review=HumanReview(
            review_type=HumanReviewType.JIRA_WRITE,
            reason="Escalate the production impact.",
            draft={"summary": "Payment API incident"},
        ),
    )

    assert accepted_human_review(report) is None

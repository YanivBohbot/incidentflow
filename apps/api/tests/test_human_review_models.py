from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReviewDecision,
    HumanReviewDecisionKind,
    HumanReviewRecommendation,
    HumanReviewRequest,
    HumanReviewType,
)


def test_review_recommendation_becomes_json_safe_request() -> None:
    recommendation = HumanReviewRecommendation(
        review_type=HumanReviewType.JIRA_WRITE,
        reason="Create an incident ticket for the confirmed production impact.",
        evidence_references=["jira:OPS-42", "mongodb:event-17"],
        draft={"summary": "Payment API incident"},
    )

    request = HumanReviewRequest.from_recommendation(recommendation)

    assert request.review_type is HumanReviewType.JIRA_WRITE
    assert request.draft == {"summary": "Payment API incident"}
    assert request.model_dump(mode="json")["evidence_references"] == [
        "jira:OPS-42",
        "mongodb:event-17",
    ]


def test_decision_can_include_an_operator_edited_draft() -> None:
    decision = HumanReviewDecision(
        decision=HumanReviewDecisionKind.APPROVE,
        actor="on-call-operator",
        edited_draft={"summary": "Approved payment API incident"},
    )

    assert decision.decision is HumanReviewDecisionKind.APPROVE
    assert decision.model_dump(mode="json")["edited_draft"] == {
        "summary": "Approved payment API incident"
    }


def test_investigation_report_defaults_to_no_review_recommendation() -> None:
    report = InvestigationReport(summary="No action requires a human review.", confidence=0.9)

    assert report.review_recommendation is None

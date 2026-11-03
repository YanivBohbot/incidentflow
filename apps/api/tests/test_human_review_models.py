from incidentflow.agent.findings import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReview,
    HumanReviewDecision,
    HumanReviewDecisionKind,
    HumanReviewType,
)


def test_human_review_is_json_safe() -> None:
    review = HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason="Create an incident ticket for the confirmed production impact.",
        evidence_references=["jira:OPS-42", "mongodb:event-17"],
        draft={"summary": "Payment API incident"},
    )

    assert review.review_type is HumanReviewType.JIRA_WRITE
    assert review.draft == {"summary": "Payment API incident"}
    assert review.model_dump(mode="json")["evidence_references"] == [
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


def test_investigation_report_defaults_to_no_human_review() -> None:
    report = InvestigationReport(summary="No action requires a human review.", confidence=0.9)

    assert report.human_review is None

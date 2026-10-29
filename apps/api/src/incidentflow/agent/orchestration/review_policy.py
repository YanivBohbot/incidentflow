"""Deterministic checks that decide whether a report may pause for review."""

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import (
    HumanReviewRequest,
    HumanReviewType,
)


def build_human_review_request(report: InvestigationReport) -> HumanReviewRequest | None:
    """Accept only policy-compliant review recommendations from a structured report."""
    recommendation = report.review_recommendation
    if recommendation is None:
        return None
    if (
        recommendation.review_type is HumanReviewType.JIRA_WRITE
        and not recommendation.evidence_references
    ):
        return None
    return HumanReviewRequest.from_recommendation(recommendation)

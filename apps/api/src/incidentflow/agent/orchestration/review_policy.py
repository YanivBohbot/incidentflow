"""Deterministic checks that decide whether a report may pause for review."""

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.domain.human_review.models import HumanReview, HumanReviewType


def accepted_human_review(report: InvestigationReport) -> HumanReview | None:
    """Return the review only when deterministic policy permits a workflow pause."""
    review = report.human_review
    if review is None:
        return None
    if (
        review.review_type is HumanReviewType.JIRA_WRITE
        and not review.evidence_references
    ):
        return None
    return review

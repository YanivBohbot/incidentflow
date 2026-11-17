"""Deterministic ceiling on the supervisor's confidence, applied when its report is captured.

The model tends to report 95-100% even on thin evidence, so the stored confidence is capped by
how well the causal chain is supported and the reason is added to the report's limitations.
"""

import re

from incidentflow.agent.findings import InvestigationReport

SYNTHETIC_CAP = 0.7
HYPOTHESIS_CAP = 0.8
SINGLE_SOURCE_CAP = 0.9


def _specialists(source: str) -> set[str]:
    """Split "ask_github, cloudwatch" into {"github", "cloudwatch"}."""
    parts = re.split(r"[,;&+]|\band\b", source.casefold())
    return {part.strip().removeprefix("ask_") for part in parts if part.strip()}


def _ceiling(report: InvestigationReport) -> tuple[float, str] | None:
    """Return the strictest cap that applies and why, or None for a well-supported report."""
    synthetic = any(item.source_status == "simulated" for item in report.evidence) or any(
        "synthetic" in limitation.casefold() for limitation in report.limitations
    )
    if synthetic:
        return SYNTHETIC_CAP, "the explanation relies on synthetic or simulated data"
    unavailable = any(item.source_status == "unavailable" for item in report.evidence)
    if unavailable or any(not step.verified for step in report.causal_chain):
        return HYPOTHESIS_CAP, "part of the chain is a hypothesis or a source was unavailable"
    cited = [step.source for step in report.causal_chain] or [
        item.source for item in report.evidence
    ]
    sources = set().union(*(_specialists(source) for source in cited))
    if len(sources) < 2:
        return SINGLE_SOURCE_CAP, "the causal chain rests on one source"
    return None


def cap_confidence(report: InvestigationReport) -> InvestigationReport:
    """Lower the confidence to the applicable ceiling and record why, at most once."""
    ceiling = _ceiling(report)
    if ceiling is None or report.confidence <= ceiling[0]:
        return report
    cap, reason = ceiling
    note = f"Confidence capped at {round(cap * 100)}%: {reason}."
    limitations = report.limitations if note in report.limitations else [*report.limitations, note]
    return report.model_copy(update={"confidence": cap, "limitations": limitations})

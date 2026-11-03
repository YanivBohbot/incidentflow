"""Structured outputs of the agents.

Each specialist returns one *Finding (its create_agent response_format). The supervisor merges
them into an InvestigationReport, which is persisted with the investigation.
"""

from incidentflow.agent.findings.cloudwatch import (
    CloudWatchAlarm,
    CloudWatchFinding,
    CloudWatchLogEvent,
    CloudWatchMetricObservation,
    CloudWatchTimeWindow,
    RootCauseHypothesis,
)
from incidentflow.agent.findings.data_intelligence import DataIntelligenceFinding
from incidentflow.agent.findings.evidence import InvestigationEvidence
from incidentflow.agent.findings.github import GitHubFinding
from incidentflow.agent.findings.it_operations import ITOperationsFinding
from incidentflow.agent.findings.knowledge import KnowledgeFinding
from incidentflow.agent.findings.report import InvestigationReport

__all__ = [
    "CloudWatchAlarm",
    "CloudWatchFinding",
    "CloudWatchLogEvent",
    "CloudWatchMetricObservation",
    "CloudWatchTimeWindow",
    "DataIntelligenceFinding",
    "GitHubFinding",
    "ITOperationsFinding",
    "InvestigationEvidence",
    "InvestigationReport",
    "KnowledgeFinding",
    "RootCauseHypothesis",
]

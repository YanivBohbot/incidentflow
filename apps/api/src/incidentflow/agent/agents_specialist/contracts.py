from typing import Literal

from pydantic import BaseModel, Field, model_validator

from incidentflow.domain.human_review.models import HumanReview


class InvestigationEvidence(BaseModel):
    source: str = Field(description="System or document that produced this evidence.")
    detail: str = Field(description="Exact, concise evidence returned by the source.")
    source_status: Literal["simulated", "live", "unavailable"] = Field(
        description="Whether the source is simulated, live, or unavailable during the investigation."
    )


class ITOperationsFinding(BaseModel):
    summary: str = Field(
        description="Concise operational summary based only on available evidence."
    )
    related_ticket_ids: list[str] = Field(
        default_factory=list,
        description="Related Jira or incident ticket identifiers found by the available tools.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed evidence supporting the summary.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Unverified possible causes, kept separate from evidence.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the summary, from 0.0 to 1.0.",
    )


class DataIntelligenceFinding(BaseModel):
    summary: str = Field(
        description="Concise technical summary based only on available events and logs."
    )
    timeline: list[str] = Field(
        default_factory=list,
        description="Ordered operational events relevant to the investigation.",
    )
    error_signatures: list[str] = Field(
        default_factory=list,
        description="Observed error messages, codes, or patterns.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed technical evidence.",
    )
    data_classification: Literal["production", "synthetic", "unknown"] = Field(
        default="unknown",
        description=(
            "Whether the observed event documents represent production, synthetic test data, "
            "or an unknown dataset. This is distinct from whether the MongoDB integration was live."
        ),
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Dataset or observability limitations that constrain the technical conclusion.",
    )
    suspected_root_causes: list[str] = Field(
        default_factory=list,
        description="Unverified technical explanations, separate from evidence.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the technical assessment, from 0.0 to 1.0.",
    )


class KnowledgeFinding(BaseModel):
    summary: str = Field(
        description="Concise recommendation grounded in the retrieved documentation."
    )
    relevant_documents: list[str] = Field(
        default_factory=list,
        description="Titles or stable identifiers of the retrieved documents.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed excerpts or facts retrieved from documentation.",
    )
    recommended_steps: list[str] = Field(
        default_factory=list,
        description="Read-only or approval-required next steps derived from the evidence.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Gaps, missing documents, or constraints in the available knowledge.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the documentation-grounded recommendation, from 0.0 to 1.0.",
    )


class GitHubFinding(BaseModel):
    summary: str = Field(
        description="Concise summary of recent code changes relevant to the incident."
    )
    repository: str = Field(description="Repository actually examined through GitHub MCP.")
    related_pull_requests: list[str] = Field(
        default_factory=list,
        description="Pull request identifiers or URLs returned by GitHub MCP.",
    )
    related_commits: list[str] = Field(
        default_factory=list,
        description="Commit SHAs or stable commit identifiers returned by GitHub MCP.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed GitHub observations supporting the summary.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Unverified possible links between code changes and the incident.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="GitHub access, time-window, or correlation gaps.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the code-change assessment, from 0.0 to 1.0.",
    )


class CloudWatchTimeWindow(BaseModel):
    start_time: str = Field(description="ISO 8601 UTC start of the queried window.")
    end_time: str = Field(description="ISO 8601 UTC end of the queried window.")


class CloudWatchMetricObservation(BaseModel):
    namespace: str = Field(description="CloudWatch namespace returned by the metric read.")
    metric_name: str = Field(description="Metric name returned by CloudWatch.")
    dimensions: list[str] = Field(
        default_factory=list, description="Dimensions as Name=Value strings."
    )
    observation: str = Field(
        description="What the returned datapoints show, citing values and timestamps."
    )
    evidence_reference: str = Field(description="Evidence reference this observation cites.")


class CloudWatchLogEvent(BaseModel):
    log_group: str = Field(description="Log group that returned the event.")
    timestamp: str | None = Field(default=None, description="Event timestamp from CloudWatch.")
    message: str = Field(description="Exact or truncated log message returned by CloudWatch.")
    evidence_reference: str = Field(description="Evidence reference this event cites.")


class CloudWatchAlarm(BaseModel):
    alarm_name: str = Field(description="Alarm name returned by CloudWatch.")
    state: str = Field(description="Alarm state returned by CloudWatch.")
    state_reason: str | None = Field(default=None, description="Reason returned by CloudWatch.")
    metric: str | None = Field(default=None, description="Namespace/metric watched by the alarm.")
    evidence_reference: str = Field(description="Evidence reference this alarm cites.")


class RootCauseHypothesis(BaseModel):
    hypothesis: str = Field(description="Unverified possible cause.")
    supporting_evidence: list[str] = Field(
        min_length=1,
        description="Evidence references, from the supplied list, that support the hypothesis.",
    )


class CloudWatchFinding(BaseModel):
    incident_id: str | None = Field(
        default=None, description="IncidentFlow incident identifier when one was supplied."
    )
    service_name: str | None = Field(
        default=None, description="Service investigated, when the request names one."
    )
    investigation_status: Literal["completed", "partial", "unavailable"] = Field(
        description="Whether every CloudWatch read completed, some failed, or none could run."
    )
    time_window: CloudWatchTimeWindow | None = Field(
        default=None, description="Window actually queried in CloudWatch."
    )
    summary: str = Field(description="Concise observability assessment based only on evidence.")
    observations: list[str] = Field(
        default_factory=list, description="Factual observations returned by CloudWatch."
    )
    relevant_metrics: list[CloudWatchMetricObservation] = Field(default_factory=list)
    relevant_log_events: list[CloudWatchLogEvent] = Field(default_factory=list)
    active_alarms: list[CloudWatchAlarm] = Field(default_factory=list)
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(
        default_factory=list,
        description="Unverified explanations, each tied to supporting evidence references.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Subjective estimate of how well the evidence supports the assessment, from 0.0 to "
            "1.0. It is not a calibrated statistical probability."
        ),
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Read-only checks or approval-required changes; never executed by the agent.",
    )
    evidence_references: list[str] = Field(
        default_factory=list, description="Evidence references actually used by this finding."
    )
    errors: list[str] = Field(
        default_factory=list, description="CloudWatch reads that failed, by category."
    )


class InvestigationReport(BaseModel):
    summary: str = Field(
        description="Consolidated incident assessment based on specialist findings."
    )
    agents_consulted: list[str] = Field(
        default_factory=list,
        description="Technical names of the specialists consulted for this report.",
    )
    evidence: list[InvestigationEvidence] = Field(
        default_factory=list,
        description="Source-attributed evidence collected from specialist findings.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Unverified explanations, kept separate from observed evidence.",
    )
    proposed_actions: list[str] = Field(
        default_factory=list,
        description="Recommendations only; no action is executed by this report.",
    )
    human_review: HumanReview | None = Field(
        default=None,
        description=(
            "Optional structured request for a human review; "
            "it never authorizes an action by itself."
        ),
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known gaps, conflicts, or source limitations.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the consolidated report, from 0.0 to 1.0.",
    )

    @model_validator(mode="after")
    def normalize_unavailable_source_statuses(self) -> "InvestigationReport":
        """Keep integration outages distinct from simulated or live evidence."""
        for evidence in self.evidence:
            detail = evidence.detail.casefold()
            if (
                "mcp was unavailable during this investigation" in detail
                or "retrieval was unavailable during this investigation" in detail
                or "mcp is unavailable because" in detail
            ):
                evidence.source_status = "unavailable"
        return self

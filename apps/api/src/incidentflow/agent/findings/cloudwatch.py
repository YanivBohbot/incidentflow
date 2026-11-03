"""Finding returned by the CloudWatch Observability agent."""

from typing import Literal

from pydantic import BaseModel, Field


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

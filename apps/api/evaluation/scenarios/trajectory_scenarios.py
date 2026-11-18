"""Trajectory scenarios: which specialists the supervisor must (not) delegate to."""

from evaluation.scenarios.scenario_model import (
    ALL_SPECIALISTS,
    EvaluationScenario,
    evidence,
    finding,
    scenario,
)

JIRA = "ask_it_operations"
MONGO = "ask_data_intelligence"
KNOWLEDGE = "ask_knowledge"
GITHUB = "ask_github"
CLOUDWATCH = "ask_cloudwatch"

_PAYMENT_REPO = "acme-shop/payment-api"

_KNOWLEDGE_POOL = finding(
    KNOWLEDGE,
    summary=(
        "Runbook 'MongoDB connection pool exhaustion': the failure shows as pool checkout "
        "timeouts with active connections at maxPoolSize. Confirm saturation from pool metrics "
        "before raising limits."
    ),
    relevant_documents=["Runbook: MongoDB connection pool exhaustion"],
    evidence=[
        evidence(
            "Knowledge base",
            "Runbook: investigate MongoDB connection pool exhaustion by comparing active "
            "connections with maxPoolSize and checking waitQueueTimeoutMS timeouts.",
        )
    ],
    recommended_steps=[
        "Compare active connections with maxPoolSize in the service metrics.",
        "Propose any maxPoolSize change through the approved deployment process.",
    ],
    confidence=0.9,
)

_MONGO_PAYMENT = finding(
    MONGO,
    summary=(
        "Payment API returned HTTP 500 on POST /payments while the MongoDB connection pool was "
        "saturated at 20 of 20 connections."
    ),
    timeline=[
        "2026-11-18T09:02Z database_connection_pool: 20 of 20 connections in use",
        "2026-11-18T09:04Z database_pool_timeout: requests waited more than 5 s",
        "2026-11-18T09:05Z http_500_rate: Payment API HTTP 500 rate rose to 31%",
    ],
    error_signatures=["MongoTimeoutError: Timed out while checking out a connection"],
    evidence=[
        evidence(
            "MongoDB", "http_500_rate event: Payment API HTTP 500 rate 31% on POST /payments."
        ),
        evidence("MongoDB", "database_connection_pool event: active_connections=20 limit=20."),
    ],
    data_classification="synthetic",
    suspected_root_causes=["MongoDB connection pool exhaustion"],
    confidence=0.85,
)

_JIRA_INC204 = finding(
    JIRA,
    summary=(
        "INC-204 is a High priority incident, status In Progress, about Payment API HTTP 500 "
        "errors; the latest comment says the on-call engineer is checking the database pool."
    ),
    related_ticket_ids=["INC-204"],
    evidence=[
        evidence("Jira", "INC-204: priority High, status In Progress, assignee on-call payments."),
        evidence("Jira", "INC-204 comment 2026-11-18T09:20Z: checking MongoDB pool saturation."),
    ],
    hypotheses=["Database connection pool saturation"],
    confidence=0.8,
)

_GITHUB_PAYMENT = finding(
    GITHUB,
    summary=(
        "Payment API had one merge in the last 24 hours: PR #482 reduced the MongoDB client "
        "maxPoolSize from 50 to 20."
    ),
    repository=_PAYMENT_REPO,
    related_pull_requests=["#482 Tune MongoDB client pool size"],
    related_commits=["a1f3c9e"],
    evidence=[
        evidence("GitHub", "PR #482 merged 2026-11-18T08:10Z changes maxPoolSize 50 -> 20."),
    ],
    hypotheses=["The lowered maxPoolSize made the pool saturate under normal load."],
    confidence=0.7,
)

_CLOUDWATCH_PAYMENT = finding(
    CLOUDWATCH,
    investigation_status="completed",
    service_name="payment-service",
    summary=(
        "payment-service HTTP5xxCount alarm if-payments is in ALARM with MongoDB pool timeout "
        "errors in /incidentflow/demo/payment-service."
    ),
    observations=["HTTP5xxCount peaked at 70 per minute against a threshold of 10."],
    active_alarms=[
        {
            "alarm_name": "if-payments",
            "state": "ALARM",
            "state_reason": "Threshold Crossed: 3 datapoints above 10",
            "metric": "IncidentFlow/Demo HTTP5xxCount",
            "evidence_reference": "alarm:if-payments",
        }
    ],
    relevant_log_events=[
        {
            "log_group": "/incidentflow/demo/payment-service",
            "timestamp": "2026-11-18T09:05:12Z",
            "message": "ERROR payment-service POST /payments status=500 MongoTimeoutError",
            "evidence_reference": "log:payment-service-1",
        }
    ],
    confidence=0.85,
    evidence_references=["alarm:if-payments", "log:payment-service-1"],
)

_JIRA_RESPONSE = finding(
    JIRA,
    summary="INC-204 reports Payment API HTTP 500 errors; ticket is High priority.",
    related_ticket_ids=["INC-204"],
    evidence=[evidence("Jira", "INC-204: Payment API HTTP 500 errors, priority High.")],
    confidence=0.8,
)

_GITHUB_REFUND = finding(
    GITHUB,
    summary=(
        "refund-service 3.1.0 (PR #131) lowered the payment-gateway client timeout from 10 s to "
        "2 s and was merged shortly before the 502 errors started."
    ),
    repository="acme-shop/refund-service",
    related_pull_requests=["#131 Lower payment-gateway client timeout"],
    related_commits=["7be20d4"],
    evidence=[
        evidence("GitHub", "refund-service 3.1.0 / PR #131: gateway client timeout 10 s -> 2 s."),
    ],
    hypotheses=["The 2 s timeout is shorter than the gateway's 3.4 s p95 refund latency."],
    confidence=0.8,
)

_CLOUDWATCH_REFUND = finding(
    CLOUDWATCH,
    investigation_status="completed",
    service_name="refund-service",
    summary=(
        "refund-service HTTP502Count rose from about 1 to 60 per minute after the 3.1.0 "
        "deployment; logs show GatewayTimeout after 2000ms."
    ),
    observations=["HTTP502Count crossed the threshold of 10 at 2026-11-18T08:42Z."],
    active_alarms=[
        {
            "alarm_name": "if-refunds",
            "state": "ALARM",
            "state_reason": "Threshold Crossed: 3 datapoints above 10",
            "metric": "IncidentFlow/Demo HTTP502Count",
            "evidence_reference": "alarm:if-refunds",
        }
    ],
    relevant_log_events=[
        {
            "log_group": "/incidentflow/demo/refund-service",
            "timestamp": "2026-11-18T08:43:10Z",
            "message": (
                "ERROR refund-service POST /refunds status=502 error=GatewayTimeout: "
                "payment-gateway did not answer within 2000ms"
            ),
            "evidence_reference": "log:refund-service-1",
        }
    ],
    confidence=0.85,
    evidence_references=["alarm:if-refunds", "log:refund-service-1"],
)

_KNOWLEDGE_FULL = finding(
    KNOWLEDGE,
    summary="Runbook for HTTP 500 caused by database connection pool exhaustion.",
    relevant_documents=["Runbook: MongoDB connection pool exhaustion"],
    evidence=[evidence("Knowledge base", "Check active connections against maxPoolSize first.")],
    recommended_steps=["Compare active connections with maxPoolSize."],
    confidence=0.8,
)

_MONGO_FULL = finding(
    MONGO,
    summary="INC-204 events: Payment API connection pool saturated and HTTP 500 rate elevated.",
    timeline=["2026-11-18T09:02Z pool at 20 of 20", "2026-11-18T09:05Z HTTP 500 rate 31%"],
    evidence=[evidence("MongoDB", "INC-204 window: active_connections=20 limit=20, HTTP 500 31%.")],
    data_classification="synthetic",
    suspected_root_causes=["MongoDB connection pool exhaustion"],
    confidence=0.8,
)

_GITHUB_FULL = finding(
    GITHUB,
    summary="PR #482 lowered the Payment API MongoDB maxPoolSize from 50 to 20 on 2026-11-18.",
    repository=_PAYMENT_REPO,
    related_pull_requests=["#482 Tune MongoDB client pool size"],
    evidence=[evidence("GitHub", "PR #482 merged 2026-11-18T08:10Z: maxPoolSize 50 -> 20.")],
    confidence=0.7,
)


def _only(tool: str, name: str, request: str, findings: dict[str, str], facts: tuple[str, ...]):
    return scenario(
        name,
        request,
        findings=findings,
        required={tool},
        forbidden=ALL_SPECIALISTS - {tool},
        key_facts=facts,
    )


TRAJECTORY_SCENARIOS: tuple[EvaluationScenario, ...] = (
    _only(
        KNOWLEDGE,
        "knowledge_only",
        "Retrieve the documented procedure for investigating MongoDB connection pool exhaustion. "
        "Do not inspect Jira, live operational events, or source-control changes.",
        {KNOWLEDGE: _KNOWLEDGE_POOL},
        ("MongoDB connection pool exhaustion",),
    ),
    _only(
        MONGO,
        "mongodb_only",
        "Inspect live MongoDB operational events for Payment API HTTP 500 errors. "
        "Do not inspect Jira, documentation, or source-control changes.",
        {MONGO: _MONGO_PAYMENT},
        ("Payment API", "HTTP 500"),
    ),
    _only(
        JIRA,
        "jira_only",
        "Read the Jira incident INC-204 and summarize its priority, status, and comments. "
        "Do not inspect operational events, documentation, or source-control changes.",
        {JIRA: _JIRA_INC204},
        ("INC-204",),
    ),
    _only(
        GITHUB,
        "github_only",
        "Review recent commits and pull requests for the Payment API repository. "
        "Do not inspect Jira, operational events, or documentation.",
        {GITHUB: _GITHUB_PAYMENT},
        ("Payment API",),
    ),
    _only(
        CLOUDWATCH,
        "cloudwatch_only",
        "Check the CloudWatch alarms, HTTP 5xx metrics, and error logs of payment-service. "
        "Do not inspect Jira, MongoDB events, documentation, or source-control changes.",
        {CLOUDWATCH: _CLOUDWATCH_PAYMENT},
        ("payment-service",),
    ),
    scenario(
        "full_investigation",
        "Investigate Jira incident INC-204 end to end: read its ticket context, inspect the "
        "corresponding MongoDB events, find similar response procedures, and review relevant "
        "recent GitHub changes.",
        findings={
            JIRA: _JIRA_RESPONSE,
            MONGO: _MONGO_FULL,
            KNOWLEDGE: _KNOWLEDGE_FULL,
            GITHUB: _GITHUB_FULL,
        },
        required={JIRA, MONGO, KNOWLEDGE, GITHUB},
        key_facts=("INC-204",),
    ),
    scenario(
        "cloudwatch_and_github_deploy_regression",
        "refund-service started returning HTTP 502 on POST /refunds right after release 3.1.0 "
        "was deployed. Check the CloudWatch alarms and error logs of refund-service and review "
        "the recent GitHub changes to the refund-service repository. "
        "Do not inspect Jira, MongoDB events, or documentation.",
        findings={CLOUDWATCH: _CLOUDWATCH_REFUND, GITHUB: _GITHUB_REFUND},
        required={CLOUDWATCH, GITHUB},
        forbidden={JIRA, MONGO, KNOWLEDGE},
        key_facts=("refund-service", "3.1.0"),
    ),
    scenario(
        "no_specialist_needed_greeting",
        "Hello, thanks for being available. What kinds of questions can you help with?",
        findings={},
        required=(),
        forbidden=ALL_SPECIALISTS,
    ),
)

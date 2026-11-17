"""The eight demo outage scenarios: single source of truth for alarms, logs and incidents."""

from dataclasses import dataclass

from incidentflow.domain.incidents.models import IncidentPriority

METRIC_NAMESPACE = "IncidentFlow/Demo"
JIRA_PROJECT = "SAM1"


@dataclass(frozen=True)
class Scenario:
    """One demo outage: its alarm, metrics, log lines, and the incident it creates."""

    service: str
    alarm_name: str
    metric: str
    unit: str
    baseline: tuple[int, int]
    incident: tuple[int, int]
    threshold: int
    healthy_line: str
    incident_lines: tuple[str, ...]
    title: str
    description: str
    priority: IncidentPriority

    @property
    def log_group(self) -> str:
        return f"/incidentflow/demo/{self.service}"


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        service="checkout-api",
        alarm_name="if-checkout",
        metric="HTTP503Count",
        unit="Count",
        baseline=(0, 1),
        incident=(80, 140),
        threshold=20,
        healthy_line="INFO checkout-api POST /checkout status=200 latency_ms={ms}",
        incident_lines=(
            (
                "ERROR checkout-api POST /checkout status=503 error=PoolTimeoutError: waited 5000ms "
                "for a database connection (active=200 max=200)"
            ),
            "WARN checkout-api autoscaler at max_pods=12 connections_per_pod=20",
        ),
        title="Checkout down during flash sale - checkout-api",
        description=(
            "checkout-api returns HTTP 503 on POST /checkout for about 40% of customers since the "
            "flash sale started. Check the operational events and the runbook for connection pool "
            f"exhaustion. Create a Jira issue of type Task in Jira project {JIRA_PROJECT} so the "
            "on-call team can track the outage."
        ),
        priority=IncidentPriority.CRITICAL,
    ),
    Scenario(
        service="order-service",
        alarm_name="if-orders",
        metric="ReplicaLagSeconds",
        unit="Seconds",
        baseline=(0, 2),
        incident=(300, 360),
        threshold=120,
        healthy_line="INFO order-service GET /orders/history status=200 source=replica lag_s=1",
        incident_lines=(
            (
                "WARN order-service GET /orders/history status=200 source=replica lag_s=340 "
                "orders_missing_from_replica=17"
            ),
            "INFO order-service POST /orders status=201 write_ack=primary",
        ),
        title="Customers report missing orders - order-service",
        description=(
            "Customers say their confirmed orders are missing from their order history, but "
            "order-service dashboards look healthy. Check order-service operational events and "
            "explain whether the orders were lost or only not visible."
        ),
        priority=IncidentPriority.CRITICAL,
    ),
    Scenario(
        service="auth-service",
        alarm_name="if-auth",
        metric="HTTP401Count",
        unit="Count",
        baseline=(2, 8),
        incident=(600, 900),
        threshold=100,
        healthy_line="INFO auth-service POST /token/validate status=200 kid=2026-10",
        incident_lines=(
            (
                "ERROR auth-service POST /token/validate status=401 reason=unknown_kid kid=2026-11 "
                "jwks_cache_kids=[2026-10] jwks_cache_ttl=24h"
            ),
            "WARN auth-service login failed for customer reason=token_rejected",
        ),
        title="Login failures after key rotation - auth-service",
        description=(
            "Many customers cannot log in: auth-service returns HTTP 401 since this morning's "
            "JWT signing-key rotation. Check auth-service events, recent code changes, and the "
            "incident runbook."
        ),
        priority=IncidentPriority.HIGH,
    ),
    Scenario(
        service="inventory-service",
        alarm_name="if-inventory",
        metric="OOMKillCount",
        unit="Count",
        baseline=(0, 0),
        incident=(1, 3),
        threshold=0,
        healthy_line="INFO inventory-service GET /stock status=200 version=2.4.1 memory_mib={ms}",
        incident_lines=(
            (
                "ERROR inventory-service container killed reason=OOMKilled memory_mib=2048 "
                "limit_mib=2048 version=2.4.1 stock_cache_entries=4100000"
            ),
            "ERROR inventory-service GET /stock status=502 upstream=pod_restarting",
        ),
        title="inventory-service pods restarting - OOMKilled",
        description=(
            "inventory-service pods keep restarting with OOMKilled since release 2.4.1, and stock "
            "reads fail during restarts. Check inventory-service events for a memory leak. Create "
            f"a Jira issue of type Task in Jira project {JIRA_PROJECT} for the memory leak."
        ),
        priority=IncidentPriority.HIGH,
    ),
    Scenario(
        service="refund-service",
        alarm_name="if-refunds",
        metric="HTTP502Count",
        unit="Count",
        baseline=(0, 1),
        incident=(30, 60),
        threshold=10,
        healthy_line="INFO refund-service POST /refunds status=201 gateway_ms={ms}",
        incident_lines=(
            (
                "ERROR refund-service POST /refunds status=502 error=GatewayTimeout: payment-gateway "
                "did not answer within 2000ms (client timeout lowered in 3.1.0)"
            ),
            "WARN refund-service refund queued for retry idempotency_key=present",
        ),
        title="Refund requests failing - refund-service",
        description=(
            "refund-service rejects about 25% of POST /refunds with HTTP 502, so customers cannot "
            "get their money back. Check refund-service alarms, logs, operational events, recent "
            "code changes, and the runbook for upstream payment-gateway errors. Create a Jira "
            f"issue of type Task in Jira project {JIRA_PROJECT} so the payments on-call team can "
            "track the refund outage."
        ),
        priority=IncidentPriority.HIGH,
    ),
    Scenario(
        service="payment-service",
        alarm_name="if-payments",
        metric="HTTP5xxCount",
        unit="Count",
        baseline=(0, 1),
        incident=(40, 70),
        threshold=10,
        healthy_line="INFO payment-service POST /payments status=200 latency_ms={ms}",
        incident_lines=(
            (
                "ERROR payment-service POST /payments status=500 latency_ms=5100 "
                "error=MongoTimeoutError: Timed out while checking out a connection from "
                "connection pool (maxPoolSize=20, waitQueueTimeoutMS=5000)"
            ),
            (
                "WARN payment-service mongodb connection pool exhausted "
                "in_use=20 max_pool_size=20 wait_queue=37"
            ),
        ),
        title="payment-service HTTP 500 alarm - CloudWatch",
        description=(
            "The CloudWatch alarm for payment-service HTTP 5xx errors fired. Check production "
            "alarms, metrics, and logs, plus the payment-service operational events."
        ),
        priority=IncidentPriority.MEDIUM,
    ),
    Scenario(
        service="search-api",
        alarm_name="if-search",
        metric="LatencyP95Ms",
        unit="Milliseconds",
        baseline=(150, 220),
        incident=(2000, 2600),
        threshold=1000,
        healthy_line="INFO search-api GET /search status=200 latency_ms={ms} cache=hit",
        incident_lines=(
            (
                "WARN search-api GET /search status=200 latency_ms=2400 cache=miss "
                "redis=replica-after-failover"
            ),
        ),
        title="Slow search results - search-api",
        description=(
            "search-api answers slowly: p95 latency went from about 200 ms to more than 2 s. "
            "Check search-api events for the cause and say whether it is recovering."
        ),
        priority=IncidentPriority.MEDIUM,
    ),
    Scenario(
        service="notification-service",
        alarm_name="if-notifications",
        metric="EmailThrottledCount",
        unit="Count",
        baseline=(0, 2),
        incident=(50, 90),
        threshold=30,
        healthy_line="INFO notification-service email sent status=202 type=order_confirmation",
        incident_lines=(
            (
                "WARN notification-service email provider status=429 rate_limited retry_in_s=60 "
                "backlog=12000"
            ),
            "INFO notification-service email delivered delay_minutes=15 lost=0",
        ),
        title="Delayed notification emails - notification-service",
        description=(
            "Order confirmation emails from notification-service arrive about 15 minutes late. "
            "Check notification-service events and confirm whether any email was lost."
        ),
        priority=IncidentPriority.LOW,
    ),
)

DEMO_ALARM_NAMES: tuple[str, ...] = tuple(s.alarm_name for s in SCENARIOS)

LEGACY_ALARM_NAMES: tuple[str, ...] = (
    *(f"incidentflow-demo-{s.service}" for s in SCENARIOS if s.service != "payment-service"),
    "incidentflow-demo-payment-5xx",
)

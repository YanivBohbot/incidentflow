// Synthetic operational events for the IncidentFlow demo scenarios.
// Run with: mongosh apps/api/scripts/seed_mongodb_scenarios.js
// Inserts only events whose event_id is missing. It never updates or deletes documents.
// Each scenario matches one incident created by scripts/seed_demo_scenarios.py.

const events = db.getSiblingDB("incidentflow_dev").getCollection("operational_events");
const testRun = "incidentflow-scenarios-v1";
const minutesAgo = (minutes) => new Date(Date.now() - minutes * 60 * 1000);

const scenarios = {
  // CRITICAL — capacity: flash-sale traffic exhausts the database connection pool.
  "SCN-CHECKOUT": { service: "checkout-api", events: [
    [95, "info", "traffic_spike", "Flash sale started: requests per second rose from 400 to 2100.", { rps: 2100 }],
    [90, "warning", "database_connection_pool", "Database connection pool usage reached 200 of 200 connections.", { active_connections: 200, configured_limit: 200 }],
    [88, "error", "database_pool_timeout", "Requests waited more than 5 s for a database connection.", { timeout_count: 312 }],
    [85, "error", "http_503_rate", "HTTP 503 rate on POST /checkout rose to 42%.", { error_rate_percent: 42 }],
    [80, "warning", "autoscaling", "Autoscaler reached its maximum of 12 pods; each pod opens 20 connections.", { pods: 12, max_pods: 12 }],
  ]},
  // CRITICAL — data integrity with conflicting signals: customers report lost orders, metrics look healthy.
  "SCN-ORDERS": { service: "order-service", events: [
    [70, "info", "http_2xx_rate", "POST /orders success rate is 99.9%; no 5xx errors recorded.", { success_rate_percent: 99.9 }],
    [65, "info", "database_write", "Order write acknowledgements are 100% successful.", { write_success_percent: 100 }],
    [60, "warning", "replication_lag", "Read replica lag rose to 340 seconds; order history reads use the replica.", { replica_lag_seconds: 340 }],
    [55, "info", "queue_consumer", "Order events consumer lag is 0.", { consumer_lag: 0 }],
  ]},
  // HIGH — security/auth: logins fail after a signing-key rotation.
  "SCN-AUTH": { service: "auth-service", events: [
    [50, "info", "jwt_key_rotation", "JWT signing key rotated from kid=2026-10 to kid=2026-11.", { new_kid: "2026-11" }],
    [48, "error", "http_401_rate", "HTTP 401 rate on token validation rose to 35%.", { error_rate_percent: 35 }],
    [46, "error", "jwks_cache", "Gateway JWKS cache still serves only kid=2026-10 (TTL 24 h).", { cache_ttl_hours: 24 }],
    [40, "warning", "login_failures", "Customer login failures reached 1800 per minute.", { failures_per_minute: 1800 }],
  ]},
  // HIGH — reliability: memory leak after a release.
  "SCN-INVENTORY": { service: "inventory-service", events: [
    [180, "info", "deployment", "Release 2.4.1 deployed: new in-memory stock cache.", { version: "2.4.1" }],
    [120, "warning", "memory_usage", "Pod memory grew from 610 MiB to 1.8 GiB without traffic increase.", { memory_mib: 1840, limit_mib: 2048 }],
    [100, "error", "oom_killed", "6 pods were OOMKilled in 20 minutes.", { oom_kills: 6 }],
    [95, "error", "pod_restarts", "Inventory reads returned HTTP 502 during pod restarts.", { error_rate_percent: 9 }],
  ]},
  // MEDIUM — performance: cache failover causes slow search.
  "SCN-SEARCH": { service: "search-api", events: [
    [35, "info", "cache_failover", "Redis primary failed over to a cold replica.", {}],
    [33, "warning", "cache_hit_rate", "Cache hit rate fell from 92% to 11%.", { hit_rate_percent: 11 }],
    [30, "warning", "latency_p95", "Search p95 latency rose from 180 ms to 2.4 s.", { p95_ms: 2400 }],
    [20, "info", "cache_hit_rate", "Cache hit rate recovering: 54%.", { hit_rate_percent: 54 }],
  ]},
  // HIGH — dependency failure: the payment gateway times out on refunds after a client change.
  "SCN-REFUND": { service: "refund-service", events: [
    [75, "info", "deployment", "refund-service 3.1.0 deployed: payment-gateway client timeout lowered from 10 s to 2 s.", { version: "3.1.0", gateway_timeout_ms: 2000 }],
    [60, "warning", "gateway_latency", "Payment-gateway refund endpoint p95 latency is 3.4 s.", { p95_ms: 3400 }],
    [58, "error", "http_502_rate", "HTTP 502 rate on POST /refunds rose to 25% (gateway timeouts).", { error_rate_percent: 25 }],
    [50, "warning", "refund_queue", "1,240 failed refunds are waiting for retry with their idempotency keys.", { pending_refunds: 1240 }],
  ]},
  // LOW — degraded non-critical feature: email delays due to provider throttling.
  "SCN-NOTIFY": { service: "notification-service", events: [
    [45, "warning", "smtp_throttling", "Email provider answered HTTP 429 (rate limit) for 18% of sends.", { throttled_percent: 18 }],
    [40, "warning", "queue_backlog", "Email queue backlog reached 12,000 messages.", { backlog: 12000 }],
    [30, "info", "delivery_delay", "Median email delivery delay is 15 minutes; no message lost.", { delay_minutes: 15 }],
  ]},
};

let inserted = 0;
let skipped = 0;
for (const [scenarioId, scenario] of Object.entries(scenarios)) {
  scenario.events.forEach(([minutes, severity, eventType, message, metrics], index) => {
    const eventId = `${scenarioId}-${String(index + 1).padStart(3, "0")}`;
    if (events.findOne({ event_id: eventId })) { skipped += 1; return; }
    events.insertOne({
      event_id: eventId,
      test_run: testRun,
      scenario_id: scenarioId,
      timestamp: minutesAgo(minutes),
      service: scenario.service,
      severity,
      event_type: eventType,
      message,
      correlation_id: `incidentflow-${scenarioId.toLowerCase()}`,
      metrics,
    });
    inserted += 1;
  });
}
print(`Synthetic scenario events: ${inserted} inserted, ${skipped} already present.`);

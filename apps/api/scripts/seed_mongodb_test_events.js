// Seed only synthetic IncidentFlow test events. This script never updates or deletes documents.

const events = db.getSiblingDB("incidentflow_dev").getCollection("operational_events");
const testRun = "incidentflow-mcp-test";

const documents = [
  {
    event_id: "IFLOW-MONGO-001",
    test_run: testRun,
    timestamp: new Date("2026-10-25T09:05:00Z"),
    service: "payment-api",
    severity: "error",
    event_type: "http_500_rate",
    message: "HTTP 500 rate increased from 0.2% to 18.7%.",
    correlation_id: "incidentflow-payment-test-001",
    metrics: { error_rate_percent: 18.7 },
  },
  {
    event_id: "IFLOW-MONGO-002",
    test_run: testRun,
    timestamp: new Date("2026-10-25T09:07:00Z"),
    service: "payment-api",
    severity: "error",
    event_type: "database_pool_timeout",
    message: "Database pool timeout errors appeared.",
    correlation_id: "incidentflow-payment-test-001",
    metrics: { timeout_count: 24 },
  },
  {
    event_id: "IFLOW-MONGO-003",
    test_run: testRun,
    timestamp: new Date("2026-10-25T09:12:00Z"),
    service: "payment-api",
    severity: "warning",
    event_type: "database_connection_pool",
    message: "Active database connections reached the configured limit.",
    correlation_id: "incidentflow-payment-test-001",
    metrics: { active_connections: 100, configured_limit: 100 },
  },
  {
    event_id: "IFLOW-MONGO-004",
    test_run: testRun,
    timestamp: new Date("2026-10-25T09:14:00Z"),
    service: "payment-api",
    severity: "error",
    event_type: "http_500_rate",
    message: "HTTP 500 rate remained above the incident threshold.",
    correlation_id: "incidentflow-payment-test-001",
    metrics: { error_rate_percent: 16.9 },
  },
  {
    event_id: "IFLOW-MONGO-005",
    test_run: testRun,
    timestamp: new Date("2026-10-25T09:16:00Z"),
    service: "payment-api",
    severity: "info",
    event_type: "incident_annotation",
    message: "Synthetic test dataset for IncidentFlow MongoDB MCP validation.",
    correlation_id: "incidentflow-payment-test-001",
    metrics: {},
  },
];

let inserted = 0;
let skipped = 0;

for (const document of documents) {
  if (events.countDocuments({ event_id: document.event_id }) === 0) {
    events.insertOne(document);
    inserted += 1;
  } else {
    skipped += 1;
  }
}

printjson({ collection: events.getName(), inserted, skipped, test_run: testRun });

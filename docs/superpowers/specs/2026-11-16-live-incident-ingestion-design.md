# Live incident ingestion from CloudWatch alarms, with a demo simulator

## Intent

Today an incident exists only when an operator types it into the dashboard
(`POST /api/incidents`). The owner wants a **demo** in which several outages appear **live** on
the dashboard, a few seconds apart, ordered, each with useful data (severity, service, source,
time). The operator looks at the severity and **decides** whether to ask the agents to run the
full investigation.

The demo must use the **real ingestion path an enterprise would use**: a CloudWatch alarm enters
`ALARM`, EventBridge delivers the state change, IncidentFlow creates the incident. Only the outage
itself is simulated. Turning the demo into an enterprise feature later means removing the
simulator and pointing the rule at real alarms; the ingestion code does not change.

## Decisions made by the owner

- Purpose: a **demo**, built on an **enterprise-ready architecture** (same chain, basic
  deduplication); enterprise extras come later.
- Outages travel through **real CloudWatch alarms and EventBridge** (option B). Without the
  simulator (real alarms) the chain must work identically.
- **The demo starts by itself when the incidents page opens** (owner's choice A), unless a demo
  run started in the last few minutes; no click needed. A "Run demo" button stays as a fallback to
  replay on demand (my call).
- Investigations start **manually**, with the existing "Start investigation" action. No
  auto-investigation.
- Ingestion: **EventBridge rule → ingest Lambda** (approach A below).
- Simulator: **asynchronously invoked demo Lambda** (approach A below).
- The dashboard keeps **polling** (no push/AppSync in this step).
- **Replaying the demo**: "Run demo" first **closes** (`CLOSED`) the open incidents of the previous
  demo run, so each run starts on a clean screen; closed incidents stay in the database.
- An **event history** (per-incident journal, every demo run with its outages, a global feed) is
  wanted, as the **next step** (see "Next step" below), not in this one.

## Goals

1. A CloudWatch alarm whose name starts with the configured prefix entering `ALARM` creates one
   incident within a few seconds of EventBridge delivery, with title, description, severity and
   service taken from the alarm.
2. An alarm that is already represented by an open incident does not create a second one
   (flapping, re-runs of the simulator while incidents are open).
3. Opening the incidents page (or clicking "Run demo") starts a run; the 8 existing demo
   scenarios go into alarm one after another,
   a few seconds apart, each with fresh logs and metric data, so the agents find real evidence.
4. The incidents page shows new incidents appearing without a reload, with their source and
   service, and the operator can start an investigation on any of them as today.

## Non-goals (this step)

- Automatic investigation by severity.
- Push to the browser (AppSync Events / WebSocket); polling stays.
- Other sources (Jira webhook, PagerDuty, Datadog) and an HTTPS ingestion webhook.
- Severity derived from thresholds/metrics; multi-team visibility.
- Refreshing MongoDB demo events per run (they stay pre-seeded by
  `scripts/seed_mongodb_scenarios.js`).
- Resolving incidents when an alarm returns to `OK`.

## Anti-goals

- A "fake" path that bypasses CloudWatch/EventBridge in the cloud deployment. The demo is
  convincing only because the chain is real.
- The demo running unattended LLM spend: nothing in this step starts an investigation.
- A public, unauthenticated endpoint. The only new route is operator-only.

## Constraints (from the project)

- The CloudWatch specialist reads only the last `CLOUDWATCH_MCP_LOOKBACK_MINUTES`; logs and metric
  points for a scenario must be written **at the moment the scenario fires**.
- Layering: routes → services → repositories; no persistence in routers. Ingestion logic lives in
  `application/services/`, not in the Lambda handler.
- Lambdas share the `jobs` image (`lambda_handlers.py`, `python -m awslambdaric`); the API runs in
  the `api` image behind the JWT authorizer with a 30 s timeout.
- The database is reached the same way the worker/sweeper reach it (`DATABASE_URL` from SSM).
- `boto3` is already a dependency; no new runtime dependency is needed.
- Ruff 100-char lines, type annotations, `test_<behavior>` names; tests need no live AWS.

## Approaches considered

**Ingestion**
- **A. EventBridge rule → ingest Lambda (chosen).** Same pattern as the sweeper (`events.Rule` →
  Lambda in the `jobs` image). Few new parts, no public endpoint.
- B. EventBridge API destination → HTTPS webhook on the API. Reusable later by Datadog/PagerDuty,
  but needs a route outside Cognito, a secret, an EventBridge connection, and the 30 s API limit.
  Can be added later next to A.

**Simulator**
- **A. Async demo Lambda (chosen).** The API invokes it with `InvocationType=Event` and returns 202;
  the Lambda plays the 8 scenarios with pauses (1–2 min total, far under 15 min).
- B. Step Functions with Wait states. Visible in the console and pausable, but a new service for
  8 steps.

## Design

### 1. Incident model

Add to `Incident` / `IncidentORM` (Alembic revision `add_incident_source`):

- `source`: enum `IncidentSource` = `MANUAL` | `CLOUDWATCH_ALARM`, default `MANUAL`
  (existing rows become `MANUAL`).
- `service`: nullable string (≤ 200).
- `external_id`: nullable string (≤ 512) — for CloudWatch, the alarm ARN.

Deduplication: a **partial unique index** on `(source, external_id)` where `external_id IS NOT
NULL` and `status IN ('OPEN', 'INVESTIGATING', 'PENDING_APPROVAL')` (Postgres `postgresql_where`;
SQLite supports partial indexes too, so repository tests exercise it). An alarm whose previous
incident is `RESOLVED`/`CLOSED` creates a new incident. The API response contract (`Incident`)
exposes the three fields; `IncidentCreate` does not (manual incidents stay `MANUAL`).

### 2. Ingestion service

`IncidentIngestionService` (in `application/services/`) with
`ingest_cloudwatch_alarm(event) -> IngestionResult` (`created` / `duplicate` / `ignored`):

- Accept only `detail-type = "CloudWatch Alarm State Change"` with
  `detail.state.value == "ALARM"`; anything else is `ignored`.
- External id = the event's `resources[0]` (alarm ARN).
- Mapping, enterprise-style (read from the alarm, never from a hard-coded scenario list):
  - **title**: tag `incidentflow:title`, else `"<alarmName> in ALARM"`;
  - **description**: `detail.configuration.description` (AlarmDescription), else the
    `detail.state.reason`; padded to satisfy the 10-char minimum;
  - **priority** (the existing `priority` field, shown as severity in the UI; nothing renamed):
    tag `incidentflow:priority` (`LOW|MEDIUM|HIGH|CRITICAL`, case-insensitive), else `MEDIUM`;
  - **service**: tag `incidentflow:service`, else the alarm name without the configured prefix.
- Tags come from `cloudwatch:ListTagsForResource` (the event does not carry tags), via a small
  injectable `AlarmTagReader` so tests use a fake.
- Insert through the repository; a unique-index violation becomes `duplicate` (no error).
  The handler logs the result as one structured line.

### 3. Ingest Lambda and EventBridge rule

- `ingest_handler(event, context)` in `lambda_handlers.py`: builds the service and calls it.
  Errors other than `duplicate` raise, so EventBridge's retry policy applies.
- CDK: `IngestFunction` (`jobs` image, 30 s, 512 MB, same DB/SSM access as the sweeper) and an
  `events.Rule` with pattern `source = aws.cloudwatch`, `detail-type = CloudWatch Alarm State
  Change`, `detail.state.value = ALARM`, `detail.alarmName` prefix = context
  `ingestAlarmPrefix` (default `if-`). IAM: `cloudwatch:ListTagsForResource`.
  Target retry: 2 attempts, max event age 5 min.

Without the simulator, any real alarm matching the prefix and carrying the tags produces the same
result — this is the enterprise path.

### 4. Demo simulator

- Move the scenario data from `scripts/seed_cloudwatch_scenarios.py` (7 scenarios),
  `scripts/seed_cloudwatch_demo.py` (payment-service) and `scripts/seed_demo_scenarios.py` into
  one package module `incidentflow/demo/scenarios.py` — **8 scenarios** (service, metric,
  thresholds, log lines, **title, description, priority**). The scripts import from it so there
  is a single source of truth. Alarm names are **short, without `demo`**: `if-<short>` with
  `if-checkout`, `if-orders`, `if-auth`, `if-inventory`, `if-search`, `if-notifications`,
  `if-refunds`, `if-payments` (owner's request). The scripts' teardown also deletes the old
  `incidentflow-demo-*` names (including `incidentflow-demo-payment-5xx`). Log groups keep their
  current `/incidentflow/demo/<service>` names, already configured in `cdk.json`. The manual `[Demo]` incidents from
  `seed_demo_scenarios.py` are no longer part of the demo; that script keeps working for manual
  mode only.
- `incidentflow/demo/simulator.py`, boto3-based (`logs`, `cloudwatch` clients injected):
  1. Generate a `run_id`. (Re)define every demo alarm with `put_metric_alarm`: the metric carries
     an extra dimension `RunId=<run_id>`, `TreatMissingData=notBreaching`, `AlarmDescription` =
     description, tags `incidentflow:title|priority|service`, `project=incidentflow`. Because the
     dimension is new, metric points from earlier runs no longer count, so an alarm can only
     enter `ALARM` from this run's data — the alarms stay **really evaluated** (not only forced),
     and the order is still guaranteed. Then set every demo alarm to `OK`.
  2. For each scenario in order: write fresh healthy + incident log lines and metric points for
     this run's dimension (timestamps relative to now), then
     `set_alarm_state(ALARM, reason=..., reasonData={"run_id": ...})` so the state change is
     immediate rather than waiting for the evaluation period; sleep the interval. Ensure log
     groups/streams exist (idempotent) before writing.
  3. The builder checks that `put_metric_alarm` on an existing alarm does not emit an
     `ALARM` state change; the rule only matches `ALARM`, so `OK`/`INSUFFICIENT_DATA` transitions
     are harmless.
- Order and pacing: scenarios ordered as in today's seed list (CRITICAL first);
  interval from `DEMO_INTERVAL_SECONDS` (default 8).
- `demo_handler(event, context)` in `lambda_handlers.py` runs the simulator.
- CDK: `DemoFunction` (`jobs` image, timeout 5 min, 256 MB, reserved concurrency 1, async
  `retry_attempts=0`, `max_event_age` 60 s) so two clicks never interleave runs. IAM limited to
  `/incidentflow/demo/*` log groups, `if-*` alarms (`PutMetricAlarm`,
  `SetAlarmState`, `TagResource`, `DescribeAlarms`) and `cloudwatch:PutMetricData` conditioned on
  the `IncidentFlow/Demo` namespace.

### 5. API

- Settings: `DEMO_ENABLED` (default false), `DEMO_FUNCTION_NAME`, `DEMO_INTERVAL_SECONDS`.
- `GET /api/demo` (viewer) → `{"enabled": bool}` so the web knows whether to show the button.
- `POST /api/demo/runs` (operator) → first, through a service (not the router), sets to `CLOSED`
  every incident with `source = CLOUDWATCH_ALARM` whose status is open and whose alarm name
  (last segment of the `external_id` ARN) is one of the 8 scenario alarms listed in
  `incidentflow/demo/scenarios.py` (exact names, not a prefix, so real alarms sharing `if-` are
  never closed); then invokes
  `DEMO_FUNCTION_NAME` asynchronously through a `DemoRunner` dependency; 202 on accept, 404 when
  demo is disabled. Closing first is what lets the next run create incidents again despite
  deduplication. Tests override the dependency. (No general "close incident" endpoint in this
  step; the history step may add one.)
- **Local mode** (my call): when `DEMO_FUNCTION_NAME` is unset, the `DemoRunner` runs the
  simulator as a FastAPI background task, and — because there is no EventBridge locally — after
  each `set_alarm_state` it passes a synthetic state-change event to the ingestion service
  directly.
- **Local credentials** (my call): the agents' local profile `incidentflow` stays read-only
  (`IncidentFlowCloudWatchReadOnly`). The simulator uses its own profile, `DEMO_AWS_PROFILE`
  (default `incidentflow-demo`), assuming a new role `IncidentFlowDemoSimulator` scoped exactly
  like the cloud `DemoFunction` (section 4); the seed script creates the role and the docs
  describe the profile. No AWS keys are exported. Known side effect, documented: if the cloud
  stack is deployed in the same account, a local run also fires the cloud EventBridge rule, so the
  cloud database receives the same incidents.
- CDK: API function gets `DEMO_ENABLED=true`, `DEMO_FUNCTION_NAME`, and `lambda:InvokeFunction`
  on the demo function only.

### 6. Dashboard

- **Auto-start**: when the incidents page opens and `GET /api/demo` says enabled, the page calls
  `POST /api/demo/runs?only_if_idle=true` once per page visit. The API starts a run only if no
  demo-alarm incident was created in the last `DEMO_AUTO_COOLDOWN_SECONDS` (default 600);
  otherwise it answers 200 `{"started": false}` and nothing changes. The cooldown is derived from
  existing incidents, so no new table is needed (the history step may add demo-run records).
  A 403 (viewer) on auto-start is silent.
- A **"Run demo"** fallback button (only when enabled) calls `POST /api/demo/runs` without the
  flag, disabled for ~10 s after a click with a "Demo running…" hint.
- Faster refresh: workspace polling goes from 10 s to **3 s while the incidents page is visible**
  (10 s elsewhere) (my call; cheap at demo scale).
- Rows show severity (existing), **service**, **source badge** ("CloudWatch alarm" / "Manual"),
  and the detection time as relative ("12 s ago"). Incidents that were not present on the
  previous refresh get a short highlight animation.
- Ordering stays as today: severity, then newest first (my call; matches the "decide by severity"
  workflow).
- "Start investigation" unchanged.

### 7. Tests

- Repository: partial unique index blocks a second open incident for the same alarm, allows one
  after `RESOLVED`.
- Ingestion service: mapping from tags/description, defaults, ignored non-ALARM events,
  duplicates.
- Simulator: botocore `Stubber` on fake clients verifies order, alarm reset, tags, fresh
  timestamps; sleep injected.
- Routes: `GET/POST /api/demo` with an overridden `DemoRunner`, role checks, disabled → 404;
  a run closes only open demo-alarm incidents (manual and non-demo alarm incidents untouched),
  and a second run then creates incidents again.
- CDK: rule pattern and target, ingest/demo functions, IAM scoping, API env + invoke grant.
- Web: button visibility, new-row highlight, source/service rendering.

## Next step: event history (separate design)

Wanted by the owner, designed and built after this step:

- a **per-incident journal** (alarm fired, incident created, investigation started, review,
  report, closed…);
- **every demo run with its outages**;
- a **global feed** of everything that happened on the platform.

This step does not build it, but keeps it possible: the simulator's `run_id` travels in the alarm
state change (`reasonData`), and incidents keep `source`/`external_id`, so the history step can
link runs, alarms and incidents without changing the ingestion chain.

## Left to the builder

- Exact column layout and styling of the new fields; highlight duration.
- Exact log lines and metric values (reuse the existing scenario data).
- Whether the ingestion service lives in `incident_service.py` or its own module.
- Error and retry details of the local background runner.

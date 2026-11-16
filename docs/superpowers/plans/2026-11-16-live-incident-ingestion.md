# Live Incident Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CloudWatch alarms entering `ALARM` become incidents through EventBridge, and opening the incidents
page (or a "Run demo" fallback button) replays 8 outage scenarios through that real chain so they appear live on the dashboard.

**Architecture:** EventBridge rule → `ingest_handler` Lambda (`jobs` image) →
`IncidentIngestionService` → `IncidentRepository` (partial unique index dedups open alarms).
`POST /api/demo/runs` closes the previous demo incidents and invokes `demo_handler` asynchronously;
the simulator writes fresh logs/metrics per run and forces each alarm into `ALARM`. The web polls
faster on the incidents page.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy + Alembic, boto3/botocore Stubber, AWS CDK
(Python), React + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-16-live-incident-ingestion-design.md`

## Global Constraints

- Ruff 100-char lines, type annotations everywhere, `test_<behavior>` names, `@pytest.mark.anyio`
  for async tests; no persistence logic in routers.
- No new runtime dependency (`boto3` already pinned `>=1.40.46,<1.40.62`).
- Tests use no live AWS: in-memory SQLite, botocore `Stubber`, fake readers/runners, CDK
  `Template` assertions.
- Alarm names: `if-checkout`, `if-orders`, `if-auth`, `if-inventory`, `if-search`,
  `if-notifications`, `if-refunds`, `if-payments`. Ingest prefix default `if-`.
- Log groups stay `/incidentflow/demo/<service>`; metric namespace stays `IncidentFlow/Demo`.
- Alarm tags: `incidentflow:title`, `incidentflow:priority`, `incidentflow:service`,
  `project=incidentflow`.
- Never export `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`; local simulator uses
  `DEMO_AWS_PROFILE` (default `incidentflow-demo`).
- Commits: concise imperative subject + the `Co-Authored-By:` / `Claude-Session:` trailers.

## Review Focus

1. **An alarm with no IncidentFlow tags** (a real alarm matching the prefix) must still create a
   readable incident: title `"<alarmName> in ALARM"`, priority `MEDIUM`, service from the name.
   Test in Task 3.
2. **Over-long or too-short alarm text**: description shorter than 10 chars is padded, title over
   200 chars truncated, description over 5000 truncated — never a validation error that makes
   EventBridge retry forever. Test in Task 3.
3. **Double click on "Run demo"**: the second request must not create a second set of incidents
   or interleave runs; the API closes nothing extra and the demo Lambda's reserved concurrency 1
   drops the overlap. Route test in Task 6 asserts closing is idempotent; CDK test in Task 7
   asserts reserved concurrency 1 and `retry_attempts=0`.
4. **A demo incident under investigation when a new run starts**: closing sets the incident to
   `CLOSED` but must not touch the investigation row. Test in Task 1.
5. **Two viewers open the page at the same moment**: both auto-start calls may pass the cooldown
   check; the reserved concurrency 1 and 60 s max event age on the demo Lambda keep at most one
   run going, and dedup keeps one incident per alarm. Covered by Task 7's CDK test and Task 1's
   dedup test; accepted for a demo.
6. **Duplicate EventBridge delivery** (at-least-once): the same event twice yields one incident,
   and the second call returns `duplicate` without raising. Test in Task 3.

---

## File Structure

API (`apps/api`):
- Modify `src/incidentflow/domain/incidents/models.py` — `IncidentSource`, new `Incident` fields,
  `AlarmIncidentCreate`.
- Modify `src/incidentflow/infrastructure/database/models.py` — `IncidentORM` columns + index.
- Create `alembic/versions/b4d6f8a0c2e4_add_incident_source.py`.
- Modify `src/incidentflow/infrastructure/database/incident_repository.py`.
- Create `src/incidentflow/demo/__init__.py`, `scenarios.py`, `simulator.py`.
- Create `src/incidentflow/application/services/incident_ingestion_service.py`.
- Create `src/incidentflow/application/services/demo_service.py` (`DemoService`, runners).
- Create `src/incidentflow/api/routes/demo.py`; modify `src/incidentflow/main.py`.
- Modify `src/incidentflow/core/config.py`, `src/incidentflow/lambda_handlers.py`.
- Modify `scripts/seed_cloudwatch_scenarios.py`, `scripts/seed_cloudwatch_demo.py`,
  `scripts/seed_demo_scenarios.py`.
- Tests: `tests/test_incident_repository.py` (create), `tests/test_demo_scenarios.py`,
  `tests/test_incident_ingestion_service.py`, `tests/test_demo_simulator.py`,
  `tests/test_demo_routes.py`, `tests/test_lambda_handlers.py` (extend).

CDK (`infra/cdk`): modify `incidentflow_cdk/stack.py`, `app.py`, `cdk.json`,
`tests/test_stack.py`.

Web (`apps/web/src`): modify `api.ts`, `hooks/useIncidentFlow.ts`, `pages/IncidentsPage.tsx`,
`App.tsx`, `App.css`, `pages/IncidentsPage.test.tsx`.

Docs: `docs/docker-local.md` (local demo profile section).

---

### Task 1: Incident source fields, migration, dedup index

**Files:**
- Modify: `apps/api/src/incidentflow/domain/incidents/models.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/models.py:20-62`
- Create: `apps/api/alembic/versions/b4d6f8a0c2e4_add_incident_source.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/incident_repository.py`
- Test: `apps/api/tests/test_incident_repository.py`

**Interfaces:**
- Produces:
  - `class IncidentSource(str, Enum): MANUAL = "MANUAL"; CLOUDWATCH_ALARM = "CLOUDWATCH_ALARM"`
  - `Incident` gains `source: IncidentSource = IncidentSource.MANUAL`, `service: str | None = None`,
    `external_id: str | None = None`.
  - `class AlarmIncidentCreate(BaseModel)`: `title: str` (5–200), `description: str` (10–5000),
    `priority: IncidentPriority`, `service: str` (≤200), `external_id: str` (≤512).
  - `class DuplicateOpenIncidentError(Exception)` in `incident_repository.py`.
  - `IncidentRepository.create_alarm_incident(data: AlarmIncidentCreate) -> Incident` — raises
    `DuplicateOpenIncidentError` on the index violation (after `session.rollback()`).
  - `IncidentRepository.close_open_alarm_incidents(alarm_names: Sequence[str]) -> int` — sets
    `CLOSED` on rows with `source=CLOUDWATCH_ALARM`, open status, and
    `external_id` ending in `:alarm:<name>` for one of the names; returns the count.
  - `OPEN_STATUSES = (OPEN, INVESTIGATING, PENDING_APPROVAL)` module constant in `models.py`
    (infrastructure) reused by the index predicate.

- [ ] **Step 1: Write the failing tests** (SQLite session fixture as in
  `tests/test_investigation_repository.py`)

```python
ARN = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:if-checkout"

def test_alarm_incident_keeps_source_service_and_external_id(repository):
    incident = repository.create_alarm_incident(alarm_data(external_id=ARN))
    assert incident.source is IncidentSource.CLOUDWATCH_ALARM
    assert incident.service == "checkout-api"
    assert incident.external_id == ARN

def test_manual_incident_defaults_to_manual_source(repository):
    assert repository.create_incident(IncidentCreate(...)).source is IncidentSource.MANUAL

def test_second_open_incident_for_same_alarm_is_rejected(repository):
    repository.create_alarm_incident(alarm_data(external_id=ARN))
    with pytest.raises(DuplicateOpenIncidentError):
        repository.create_alarm_incident(alarm_data(external_id=ARN))

def test_closed_alarm_incident_allows_a_new_one(repository):
    repository.create_alarm_incident(alarm_data(external_id=ARN))
    assert repository.close_open_alarm_incidents(["if-checkout"]) == 1
    assert repository.create_alarm_incident(alarm_data(external_id=ARN)).status is IncidentStatus.OPEN

def test_closing_ignores_manual_and_other_alarms(repository):
    manual = repository.create_incident(IncidentCreate(...))
    other = repository.create_alarm_incident(alarm_data(external_id=ARN.replace("if-checkout", "if-checkout-prod")))
    assert repository.close_open_alarm_incidents(["if-checkout"]) == 0
    assert repository.get_incident(manual.id).status is IncidentStatus.OPEN
    assert repository.get_incident(other.id).status is IncidentStatus.OPEN

def test_closing_an_incident_leaves_its_investigation_untouched(session, repository):
    incident = repository.create_alarm_incident(alarm_data(external_id=ARN))
    investigation = InvestigationRepository(session).create_investigation(incident.id, ...)  # RUNNING
    repository.close_open_alarm_incidents(["if-checkout"])
    assert InvestigationRepository(session).get_investigation(investigation.id).lifecycle is investigation.lifecycle
```

- [ ] **Step 2: Run** `pytest tests/test_incident_repository.py -v` → FAIL (`IncidentSource` not
  defined).

- [ ] **Step 3: Implement.** ORM: `source` `Enum(IncidentSource, name="incident_source")`
  non-null default `MANUAL`, `service String(200)` null, `external_id String(512)` null;
  `__table_args__ = (Index("uq_incidents_open_external", "source", "external_id", unique=True,
  postgresql_where=..., sqlite_where=...),)` with predicate
  `external_id IS NOT NULL AND status IN ('OPEN', 'INVESTIGATING', 'PENDING_APPROVAL')`.
  Migration `b4d6f8a0c2e4`, `down_revision = "a7c9e1f3b5d8"`: create the enum type, add columns
  (`source` with `server_default='MANUAL'`), create the index; downgrade reverses and drops the
  enum. Repository: `to_domain` maps the three fields; `create_alarm_incident` catches
  `IntegrityError`.

- [ ] **Step 4: Run** `pytest tests/test_incident_repository.py tests/test_migrate.py -v` → PASS;
  `pytest -q` → all pass.

- [ ] **Step 5: Commit** `Record where an incident came from and dedup open alarm incidents`.

---

### Task 2: Demo scenarios module (single source of truth)

**Files:**
- Create: `apps/api/src/incidentflow/demo/__init__.py`, `apps/api/src/incidentflow/demo/scenarios.py`
- Modify: `apps/api/scripts/seed_cloudwatch_scenarios.py`, `apps/api/scripts/seed_cloudwatch_demo.py`,
  `apps/api/scripts/seed_demo_scenarios.py`
- Test: `apps/api/tests/test_demo_scenarios.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Scenario`: `service: str`, `alarm_name: str`, `metric: str`,
    `unit: str`, `baseline: tuple[int, int]`, `incident: tuple[int, int]`, `threshold: int`,
    `healthy_line: str`, `incident_lines: tuple[str, ...]`, `title: str`, `description: str`,
    `priority: IncidentPriority`; property `log_group -> "/incidentflow/demo/<service>"`.
  - `SCENARIOS: tuple[Scenario, ...]` — 8 items, CRITICAL first, in today's
    `seed_demo_scenarios.py` order.
  - `DEMO_ALARM_NAMES: tuple[str, ...]`, `METRIC_NAMESPACE = "IncidentFlow/Demo"`,
    `LEGACY_ALARM_NAMES` (the old `incidentflow-demo-*` names incl.
    `incidentflow-demo-payment-5xx`).

- [ ] **Step 1: Write the failing tests**

```python
def test_scenarios_cover_the_eight_demo_services():
    assert [s.alarm_name for s in SCENARIOS] == ["if-checkout", "if-orders", "if-auth",
        "if-inventory", "if-refunds", "if-payments", "if-search", "if-notifications"]

def test_scenario_texts_fit_incident_and_alarm_limits():
    for s in SCENARIOS:
        assert 5 <= len(s.title) <= 200 and len(s.title) <= 256   # tag value limit
        assert 10 <= len(s.description) <= 1024                    # AlarmDescription limit

def test_scenarios_start_with_critical_outages():
    assert SCENARIOS[0].priority is IncidentPriority.CRITICAL
```

  (Order is today's `seed_demo_scenarios.py` order.)

- [ ] **Step 2: Run** `pytest tests/test_demo_scenarios.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement** by moving data from the three scripts (titles drop the `[Demo] `
  prefix). Scripts import `SCENARIOS`; their teardown also deletes `LEGACY_ALARM_NAMES`;
  `seed_demo_scenarios.py` keeps creating manual incidents (manual mode only) from the same data.

- [ ] **Step 4: Run** `pytest tests/test_demo_scenarios.py -v` → PASS; `ruff check src tests scripts`.

- [ ] **Step 5: Commit** `Keep the demo scenarios in one module with short alarm names`.

---

### Task 3: Ingestion service

**Files:**
- Create: `apps/api/src/incidentflow/application/services/incident_ingestion_service.py`
- Test: `apps/api/tests/test_incident_ingestion_service.py`

**Interfaces:**
- Consumes: `IncidentRepository.create_alarm_incident`, `DuplicateOpenIncidentError` (Task 1).
- Produces:
  - `class AlarmTagReader(Protocol): def tags_for(self, alarm_arn: str) -> dict[str, str]: ...`
  - `class CloudWatchAlarmTagReader` (boto3 `cloudwatch.list_tags_for_resource(ResourceARN=...)`),
    constructor `(client: Any)`.
  - `class IngestionOutcome(str, Enum): CREATED, DUPLICATE, IGNORED`
  - `@dataclass(frozen=True) class IngestionResult: outcome: IngestionOutcome; incident: Incident | None`
  - `IncidentIngestionService(repository, tag_reader, alarm_prefix: str)` with
    `ingest_cloudwatch_alarm(event: dict[str, Any]) -> IngestionResult`.

- [ ] **Step 1: Write the failing tests** (fake tag reader; event fixture shaped like a real
  "CloudWatch Alarm State Change": `resources[0]` ARN, `detail.alarmName`, `detail.state.value`,
  `detail.state.reason`, `detail.configuration.description`)

```python
def test_alarm_event_creates_incident_from_tags(service):
    result = service.ingest_cloudwatch_alarm(alarm_event("if-checkout", tags={
        "incidentflow:title": "Checkout down", "incidentflow:priority": "critical",
        "incidentflow:service": "checkout-api"}, description="checkout-api returns 503 ..."))
    assert result.outcome is IngestionOutcome.CREATED
    assert (result.incident.title, result.incident.priority, result.incident.service) == (
        "Checkout down", IncidentPriority.CRITICAL, "checkout-api")

def test_untagged_alarm_falls_back_to_name_and_medium(service):
    result = service.ingest_cloudwatch_alarm(alarm_event("if-billing", tags={}, description=None,
        reason="Threshold Crossed: 1 datapoint [5.0] was greater than 1.0"))
    assert result.incident.title == "if-billing in ALARM"
    assert result.incident.priority is IncidentPriority.MEDIUM
    assert result.incident.service == "billing"
    assert result.incident.description.startswith("Threshold Crossed")

def test_short_and_long_texts_are_fitted():
    # description "x" -> length >= 10; title of 300 chars -> 200 chars
def test_non_alarm_state_is_ignored(service):   # state.value "OK" -> IGNORED, no row
def test_other_detail_type_is_ignored(service):
def test_same_event_twice_is_a_duplicate(service):
    service.ingest_cloudwatch_alarm(event); second = service.ingest_cloudwatch_alarm(event)
    assert second.outcome is IngestionOutcome.DUPLICATE and len(repository.list_incidents()) == 1
def test_unknown_priority_tag_falls_back_to_medium(service):
```

- [ ] **Step 2: Run** `pytest tests/test_incident_ingestion_service.py -v` → FAIL.

- [ ] **Step 3: Implement.** Padding rule: if description < 10 chars, append
  `" (CloudWatch alarm <name>)"`. Service fallback: alarm name with `alarm_prefix` stripped. Log
  one line `ingested alarm=<name> outcome=<outcome> incident=<id>`.

- [ ] **Step 4: Run** the file → PASS.

- [ ] **Step 5: Commit** `Turn CloudWatch alarm state changes into incidents`.

---

### Task 4: Ingest Lambda handler

**Files:**
- Modify: `apps/api/src/incidentflow/core/config.py` (add `ingest_alarm_prefix: str = "if-"`)
- Modify: `apps/api/src/incidentflow/lambda_handlers.py`
- Test: `apps/api/tests/test_lambda_handlers.py`

**Interfaces:**
- Consumes: Task 3 service.
- Produces: `ingest_handler(event: dict[str, Any], context: Any) -> dict[str, str]` returning
  `{"outcome": "<CREATED|DUPLICATE|IGNORED>"}`; module attribute
  `alarm_tag_reader_factory: Callable[[], AlarmTagReader]` (default builds
  `CloudWatchAlarmTagReader(boto3.client("cloudwatch"))`) so tests replace it, like
  `session_factory_provider`. Update the module docstring to list the ingest and demo handlers.

- [ ] **Step 1: Write the failing tests**

```python
def test_ingest_handler_creates_incident(monkeypatch, sqlite_session_factory):
    monkeypatch.setattr(lambda_handlers, "session_factory_provider", lambda: sqlite_session_factory)
    monkeypatch.setattr(lambda_handlers, "alarm_tag_reader_factory", lambda: FakeTags({}))
    assert lambda_handlers.ingest_handler(alarm_event("if-checkout"), None) == {"outcome": "CREATED"}

def test_ingest_handler_reports_duplicate_without_raising(...):
```

- [ ] **Step 2: Run** `pytest tests/test_lambda_handlers.py -k ingest -v` → FAIL.
- [ ] **Step 3: Implement** (`_load_environment()`, one session per invocation, closed after).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the alarm ingestion Lambda handler`.

---

### Task 5: Demo simulator

**Files:**
- Create: `apps/api/src/incidentflow/demo/simulator.py`
- Test: `apps/api/tests/test_demo_simulator.py`

**Interfaces:**
- Consumes: `SCENARIOS`, `METRIC_NAMESPACE` (Task 2).
- Produces:
  - `AlarmFired = Callable[[Scenario, str], None]` (scenario, run_id) — hook for local mode.
  - `class DemoSimulator(logs_client: Any, cloudwatch_client: Any, *, interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep, now: Callable[[], datetime] = ...,
    on_alarm_fired: AlarmFired | None = None)` with `run(run_id: str) -> None`.
  - `def alarm_arn(region: str, account: str, alarm_name: str) -> str` helper (used by local mode
    to build synthetic events).

- [ ] **Step 1: Write the failing tests** (botocore `Stubber` on real `boto3.client("logs")` /
  `("cloudwatch")` with region `us-east-1` and dummy credentials; `sleep` records calls)

```python
def test_run_redefines_alarms_with_run_dimension_then_resets_them(stubbed):
    # expect 8 put_metric_alarm with Dimensions containing {"Name": "RunId", "Value": "r1"},
    # TreatMissingData="notBreaching", AlarmDescription=scenario.description, the 4 tags;
    # then 8 set_alarm_state(StateValue="OK") before any ALARM
def test_run_fires_alarms_in_scenario_order_with_interval(stubbed):
    # ALARM set_alarm_state calls in SCENARIOS order; StateReasonData == '{"run_id": "r1"}';
    # sleep called 7 times with interval_seconds (none after the last)
def test_run_writes_fresh_logs_and_metrics_before_each_alarm(stubbed):
    # put_log_events timestamps within the last 10 min of now(); put_metric_data uses the RunId
    # dimension and METRIC_NAMESPACE, before that scenario's ALARM call
def test_on_alarm_fired_is_called_after_each_alarm(stubbed):
```

- [ ] **Step 2: Run** `pytest tests/test_demo_simulator.py -v` → FAIL.
- [ ] **Step 3: Implement.** Log groups/streams created idempotently
  (`ResourceAlreadyExistsException` ignored); stream name `run-<run_id>`; retention 1 day.
  Check in the boto3 docs that `put_metric_alarm` on an existing alarm does not emit an `ALARM`
  state change; note the finding in a code comment.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Replay the demo outages through real CloudWatch alarms`.

---

### Task 6: Demo API, runners and demo Lambda handler

**Files:**
- Modify: `apps/api/src/incidentflow/core/config.py` — `demo_enabled: bool = False`,
  `demo_function_name: str | None = None`, `demo_interval_seconds: float = 8.0`,
  `demo_aws_profile: str = "incidentflow-demo"`.
- Create: `apps/api/src/incidentflow/application/services/demo_service.py`
- Create: `apps/api/src/incidentflow/api/routes/demo.py`; Modify `src/incidentflow/main.py:94-98`
- Modify: `apps/api/src/incidentflow/lambda_handlers.py`
- Test: `apps/api/tests/test_demo_routes.py`, `apps/api/tests/test_lambda_handlers.py`

**Interfaces:**
- Consumes: Task 1 `close_open_alarm_incidents`, Task 2 `DEMO_ALARM_NAMES`, Task 3 service,
  Task 5 simulator.
- Produces:
  - `class DemoRunner(Protocol): def start(self, run_id: str) -> None: ...`
  - `LambdaDemoRunner(lambda_client, function_name)` — `invoke(FunctionName=...,
    InvocationType="Event", Payload=json.dumps({"run_id": run_id}))`.
  - `LocalDemoRunner(settings, session_factory, background: BackgroundTasks)` — runs
    `DemoSimulator` built from a `boto3.Session(profile_name=settings.demo_aws_profile)`, with
    `on_alarm_fired` feeding a synthetic state-change event to `IncidentIngestionService`.
  - `IncidentRepository.latest_alarm_incident_created_at(alarm_names: Sequence[str]) ->
    datetime | None` (same `:alarm:<name>` match as `close_open_alarm_incidents`, any status).
  - `DemoService(repository, runner, auto_cooldown_seconds: int, now: Callable[[], datetime])`
    with `start_run(only_if_idle: bool = False) -> DemoRunStarted` (`started: bool`,
    `run_id: str | None`, `closed_incidents: int`). With `only_if_idle` and a demo incident created
    less than `auto_cooldown_seconds` ago, returns `started=False` without closing or starting.
    Otherwise closes `DEMO_ALARM_NAMES` first, then `runner.start(run_id)`.
  - Setting `demo_auto_cooldown_seconds: int = 600`.
  - Routes: `GET /api/demo` (viewer) → `DemoStatus {enabled: bool}`; `POST /api/demo/runs`
    (operator, query `only_if_idle: bool = False`) → 202 `DemoRunStarted` when started, 200
    with `started=false` when skipped, 404 `"Demo is disabled"` when `demo_enabled` is false.
    Dependency `get_demo_runner` picks Lambda when `demo_function_name` is set, else local.
  - `demo_handler(event, context) -> dict[str, str]` → `{"run_id": ...}`; module attribute
    `demo_simulator_factory: Callable[[Settings], DemoSimulator]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_demo_status_reports_disabled_by_default(client):  # {"enabled": False}
def test_run_demo_is_404_when_disabled(operator_client):
def test_run_demo_requires_operator(viewer_client):  # 403 (pattern from tests/test_auth.py)
def test_run_demo_closes_previous_demo_incidents_and_starts_runner(operator_client, fake_runner, repository):
    repository.create_alarm_incident(alarm_data("if-checkout")); manual = repository.create_incident(...)
    response = operator_client.post("/api/demo/runs")
    assert response.status_code == 202 and response.json()["closed_incidents"] == 1
    assert fake_runner.run_ids == [response.json()["run_id"]]
    assert repository.get_incident(manual.id).status is IncidentStatus.OPEN
def test_second_run_closes_nothing_new(...):  # closed_incidents == 0, runner called twice
def test_auto_start_skips_when_a_demo_incident_is_recent(...):
    # demo incident created 5 min ago, cooldown 600 -> 200 {"started": False}, runner not called, nothing closed
def test_auto_start_runs_when_demo_is_idle(...):
    # newest demo incident 11 min ago (or none) -> 202, started True, runner called once
def test_manual_run_ignores_the_cooldown(...):  # recent demo incident, no flag -> 202
def test_lambda_runner_invokes_asynchronously():  # Stubber: InvocationType "Event", payload run_id
def test_demo_handler_runs_simulator_with_event_run_id(monkeypatch):
def test_local_runner_ingests_each_fired_alarm(...):  # fake simulator calling on_alarm_fired twice -> 2 incidents
```

- [ ] **Step 2: Run** `pytest tests/test_demo_routes.py tests/test_lambda_handlers.py -k demo -v` → FAIL.
- [ ] **Step 3: Implement** (router has no persistence; `get_settings.cache_clear()` in tests).
- [ ] **Step 4: Run** → PASS; `pytest -q`, `ruff check src tests scripts`,
  `ruff format --check src tests`.
- [ ] **Step 5: Commit** `Let an operator start a demo run from the API`.

---

### Task 7: CDK — ingest rule, ingest and demo functions

**Files:**
- Modify: `infra/cdk/incidentflow_cdk/stack.py`, `infra/cdk/app.py`, `infra/cdk/cdk.json`
- Test: `infra/cdk/tests/test_stack.py`

**Interfaces:**
- Produces: `IncidentFlowStack(..., ingest_alarm_prefix: str)`; context key
  `ingestAlarmPrefix` = `"if-"` in `cdk.json`, read with `_context` in `app.py`. Update
  `JOB_FUNCTIONS` in the test to include `IngestFunction`, `DemoFunction`.

- [ ] **Step 1: Write the failing tests**

```python
def test_alarm_rule_targets_ingest_function(template):
    template.has_resource_properties("AWS::Events::Rule", {"EventPattern": {
        "source": ["aws.cloudwatch"], "detail-type": ["CloudWatch Alarm State Change"],
        "detail": {"state": {"value": ["ALARM"]}, "alarmName": [{"prefix": "if-"}]}}})
    # target = IngestFunction, RetryPolicy MaximumRetryAttempts 2, MaximumEventAgeInSeconds 300
def test_ingest_function_can_read_alarm_tags(template):  # cloudwatch:ListTagsForResource; handler ingest_handler; 30 s; 512 MB
def test_demo_function_is_single_and_not_retried(template):
    # ReservedConcurrentExecutions 1; EventInvokeConfig MaximumRetryAttempts 0, MaximumEventAgeInSeconds 60; timeout 300; 256 MB
def test_demo_function_permissions_are_scoped(template):
    # PutMetricAlarm/SetAlarmState/TagResource/DescribeAlarms on arn:...:alarm:if-*;
    # logs writes on log-group:/incidentflow/demo/*; PutMetricData with
    # Condition StringEquals cloudwatch:namespace IncidentFlow/Demo
def test_api_can_start_demo_runs(template):
    # ApiFunction env DEMO_ENABLED=true, DEMO_FUNCTION_NAME=<ref>; lambda:InvokeFunction on DemoFunction only
```

- [ ] **Step 2: Run** `cd infra/cdk; .venv/Scripts/python -m pytest -q` → FAIL.
- [ ] **Step 3: Implement** with `self._function(...)` (handlers `ingest_handler`, `demo_handler`,
  ingest env as the sweeper's), `events.Rule` + `targets.LambdaFunction(retry_attempts=2,
  max_event_age=Duration.minutes(5))`, `DemoFunction` with `reserved_concurrent_executions=1`,
  `retry_attempts=0`, `max_event_age=Duration.seconds(60)`, env `DEMO_INTERVAL_SECONDS="8"`.
- [ ] **Step 4: Run** → PASS; `ruff check .`, `ruff format --check .`.
- [ ] **Step 5: Commit** `Deploy the alarm ingestion rule and the demo simulator`.

---

### Task 8: Local demo credentials and docs

**Files:**
- Modify: `apps/api/scripts/seed_cloudwatch_demo.py` (or the script that creates
  `IncidentFlowCloudWatchReadOnly`) — add `--create-demo-role` creating `IncidentFlowDemoSimulator`
  with the same permissions as Task 7's `DemoFunction`, tagged `project=incidentflow`.
- Modify: `docs/docker-local.md`, `apps/api/.env.example`, `docker-compose.cloudwatch.yml`
  (pass `DEMO_ENABLED`, `DEMO_AWS_PROFILE`).
- Test: a unit test asserting the role policy document the script builds equals the expected
  actions/resources (pure function `demo_role_policy(account: str, region: str) -> dict`).

- [ ] **Step 1: Write** `test_demo_role_policy_matches_cloud_permissions` → run → FAIL.
- [ ] **Step 2: Implement** `demo_role_policy` and the flag; document the `incidentflow-demo`
  profile (`role_arn` + `source_profile`), `DEMO_ENABLED=true`, and the same-account side effect
  (a local run also creates incidents in the cloud database when the stack is deployed).
- [ ] **Step 3: Run** the test → PASS; `ruff check src tests scripts`.
- [ ] **Step 4: Commit** `Give the local demo its own scoped AWS role`.

---

### Task 9: Dashboard — Run demo, live refresh, source and service

**Files:**
- Modify: `apps/web/src/api.ts`, `apps/web/src/hooks/useIncidentFlow.ts:12,96`,
  `apps/web/src/pages/IncidentsPage.tsx`, `apps/web/src/App.tsx:39`, `apps/web/src/App.css`
- Test: `apps/web/src/pages/IncidentsPage.test.tsx`

**Interfaces:**
- Consumes: Task 6 routes.
- Produces: `Incident` type gains `source: 'MANUAL' | 'CLOUDWATCH_ALARM'`, `service: string | null`,
  `external_id: string | null`; `api.getDemoStatus(): Promise<{enabled: boolean}>`,
  `api.startDemoRun(): Promise<{run_id: string; closed_incidents: number}>`; hook exposes
  `demoEnabled: boolean`, `startDemoRun(): Promise<void>`, `isDemoStarting: boolean`;
  `api.startDemoRun(onlyIfIdle = false)` adds `?only_if_idle=true`; the response type gains
  `started: boolean` and `run_id: string | null`; the hook exposes
  `autoStartDemo(): Promise<void>` (calls with `onlyIfIdle=true`, swallows 403);
  `useIncidentFlow` takes the active page so refresh is `3_000` ms on `'incidents'`, `10_000` ms
  elsewhere. `IncidentsPage` props gain `demoEnabled`, `isDemoStarting`, `onRunDemo`.

The web has no role information; the button shows whenever the demo is enabled and a 403 is
surfaced through the existing status message (my call, deviation from "operator only" display).

- [ ] **Step 1: Write the failing tests**

```tsx
it('auto-starts the demo once when the incidents page opens and the demo is enabled', ...)  // startDemoRun(true) called once, not again on rerender
it('does not auto-start when the demo is disabled', ...)
it('shows Run demo only when the demo is enabled', ...)
it('disables Run demo for 10 seconds after a click and shows "Demo running…"', ...)  // fake timers
it('shows the service and a CloudWatch alarm badge for alarm incidents', ...)        // "checkout-api", "CloudWatch alarm"
it('shows a Manual badge for manual incidents', ...)
it('highlights incidents that were not in the previous list', ...)                   // class "is-new" on rerender with a new id, not on the first render
it('shows detection time relative to now', ...)                                      // "12 s ago" with mocked Date.now
```

- [ ] **Step 2: Run** `npm test -- IncidentsPage` (from `apps/web`) → FAIL.
- [ ] **Step 3: Implement.** Highlight lasts 4 s (`is-new` CSS animation); ordering unchanged
  (`bySeverityThenDate`).
- [ ] **Step 4: Run** `npm test`, `npm run lint`, `npm run build` → all pass.
- [ ] **Step 5: Commit** `Show alarm incidents arriving live and add a Run demo button`.

---

### Task 10: End-to-end check against AWS (manual, owner present)

- [ ] Locally: create the demo role (`--create-demo-role`), configure the profile, set
  `DEMO_ENABLED=true`, `docker compose up --build -d`, open the incidents page (no click):
  8 incidents appear about 8 s apart, CRITICAL first; reloading the page within 10 min starts
  nothing new; start an investigation on `if-checkout` and confirm the CloudWatch
  specialist finds the fresh 503 log lines.
- [ ] Click "Run demo" again: the previous 8 are `CLOSED`, 8 new ones appear.
- [ ] Record results in the PR description; nothing deployed to the cloud without the owner.

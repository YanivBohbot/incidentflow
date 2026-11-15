# Investigation Job Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept investigations with `202` and execute them in separate, crash-safe workers fed by an SQS-compatible queue.

**Architecture:** The `investigations` row is the job record; every lifecycle transition is a conditional update fenced by a per-claim `lease_token`. The API writes the row and sends `{"investigation_id"}` to the queue; a worker claims the row, derives what to run from the LangGraph checkpoint, heartbeats its lease, and persists the result. A sweeper re-sends stale rows.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, LangGraph (`AsyncPostgresSaver` / `InMemorySaver`), boto3 + ElasticMQ, React/Vite.

**Spec:** `docs/superpowers/specs/2026-11-15-investigation-job-queue-design.md`

## Global Constraints

- Python commands run from `apps/api` with `.venv/Scripts/python.exe` (e.g. `.venv/Scripts/python.exe -m pytest -q`). Baseline before Task 1: 161 passed, 2 skipped.
- Ruff line limit 100; type annotations on new code; test names `test_<behavior>`; async tests use `@pytest.mark.anyio`.
- No test may need AWS credentials, network, Postgres, or OpenAI (SQS tests use `botocore.stub.Stubber`).
- Defaults: `JOB_LEASE_SECONDS=300`, `JOB_MAX_ATTEMPTS=3`, `WORKER_CONCURRENCY=2`, sweeper every 60 s, stale `PENDING` threshold 120 s, DLQ after 3 receives.
- Never resume an approved `JIRA_WRITE` when the job was claimed with `attempt_count > 1`; fail with `JIRA_OUTCOME_UNKNOWN_MESSAGE` (Task 3).
- All timestamps written and compared in UTC (`incidentflow.domain.investigations.models.utc_now`).
- No changes under `agent/agents_specialist`, `agent/prompts`, `agent/mcp_clients`, `agent/guardrails`.
- Commits: concise imperative subject, ending with the session's `Co-Authored-By:` / `Claude-Session:` trailer lines.

## Review Focus

1. Worker dies after the graph finished but before persisting → the next claim persists from the checkpoint and runs nothing (Task 3, `test_finished_checkpoint_is_persisted_without_running`).
2. The queue `send` raises after the row was committed → API still returns 202, row stays `PENDING`, sweeper re-sends it (Task 4 `test_start_returns_202_when_queue_send_fails`; Task 5 sweeper test).
3. Operator double-clicks "approve" → second resolve gets 409 and nothing is enqueued twice (Task 4, `test_second_resolve_is_rejected_with_409`).
4. The workflow raises inside `ainvoke` → investigation `FAILED`, message acknowledged, no endless redelivery (Task 3 `test_workflow_exception_fails_and_is_not_retried`; Task 5 ack test).
5. Message for an unknown or already-terminal investigation → dropped and acknowledged (Task 3 `test_unknown_or_terminal_investigation_is_dropped`).

---

### Task 1: Lease-fenced investigation repository

**Files:**
- Create: `apps/api/alembic/versions/f1a2b3c4d5e6_add_investigation_job_lease.py` (down_revision `d3e9a6b1f4c7`)
- Modify: `apps/api/src/incidentflow/infrastructure/database/models.py` (`InvestigationORM`)
- Modify: `apps/api/src/incidentflow/infrastructure/database/investigation_repository.py`
- Delete: `apps/api/src/incidentflow/application/services/investigation_recovery.py`, `apps/api/tests/test_investigation_recovery.py`
- Test: `apps/api/tests/test_investigation_job_repository.py`

**Interfaces:**
- Produces, in `investigation_repository.py`:
  - `@dataclass(frozen=True) class ClaimedInvestigation: investigation: Investigation; lease_token: str; attempt_count: int; resume_payload: dict | None`
  - `InvestigationRepository.has_active_investigation(incident_id: UUID) -> bool` (`PENDING` or `RUNNING`)
  - `claim(investigation_id: UUID, *, lease_seconds: int, now: datetime | None = None) -> ClaimedInvestigation | None`
  - `heartbeat(investigation_id: UUID, lease_token: str, *, lease_seconds: int, now: datetime | None = None) -> bool`
  - `complete_investigation(investigation_id, report, *, lease_token: str) -> Investigation | None`
  - `mark_awaiting_human_review(investigation_id, report, review, *, lease_token: str) -> Investigation | None`
  - `fail_investigation(investigation_id, error_message, *, lease_token: str) -> Investigation | None`
  - `request_resume(investigation_id: UUID, resume_payload: dict) -> Investigation | None` (`AWAITING_HUMAN_REVIEW → PENDING`)
  - `stale_investigation_ids(*, pending_older_than_seconds: int, now: datetime | None = None) -> list[UUID]`
  - `count_by_lifecycle() -> dict[str, int]`
- Removes: `mark_running`, `fail_running_investigations`.

- [ ] **Step 1: Write the failing tests** (SQLite + `Base.metadata.create_all`, like `test_investigation_repository.py`)

```python
def test_claim_applies_once_and_fences_writes():
    first = repo.claim(inv.id, lease_seconds=300)
    assert first.attempt_count == 1 and first.investigation.lifecycle is RUNNING
    assert repo.claim(inv.id, lease_seconds=300) is None          # lease still valid
    assert repo.complete_investigation(inv.id, report, lease_token="other") is None
    assert repo.complete_investigation(inv.id, report, lease_token=first.lease_token).lifecycle is COMPLETED

def test_expired_lease_is_reclaimed_and_stale_writer_ignored():
    first = repo.claim(inv.id, lease_seconds=300, now=t0)
    second = repo.claim(inv.id, lease_seconds=300, now=t0 + timedelta(seconds=301))
    assert second.attempt_count == 2 and second.lease_token != first.lease_token
    assert repo.fail_investigation(inv.id, "late", lease_token=first.lease_token) is None
    assert repo.heartbeat(inv.id, first.lease_token, lease_seconds=300) is False

def test_request_resume_requeues_and_resets_attempts():
    # claim, mark_awaiting_human_review(..., lease_token=...), then:
    queued = repo.request_resume(inv.id, {"command_resume": {"decisions": [{"type": "approve"}]}})
    assert queued.lifecycle is PENDING
    assert repo.request_resume(inv.id, {}) is None                # no longer awaiting
    assert repo.claim(inv.id, lease_seconds=300).attempt_count == 1
    assert repo.claim(...)  # resume_payload of that claim equals the stored payload

def test_has_active_investigation(): ...   # True for PENDING/RUNNING, False after COMPLETED

def test_stale_ids_cover_old_pending_and_expired_running():
    # fresh PENDING excluded; PENDING updated 121 s ago included; RUNNING with expired lease included

def test_count_by_lifecycle(): assert repo.count_by_lifecycle() == {"PENDING": 1, "COMPLETED": 2}
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_investigation_job_repository.py -q` → FAIL (`claim` not defined).

- [ ] **Step 3: Implement.** ORM gains `lease_token: String(36) | None`, `lease_expires_at: DateTime(timezone=True) | None`, `attempt_count: int` (server_default `0`), `pending_resume_payload: JSON | None`; migration adds the four columns and drops nothing. Each transition is one `update(InvestigationORM).where(id, lifecycle == expected[, lease_token == token]).values(...)` checking `rowcount == 1`, then re-reads. `claim` matches `lifecycle == PENDING OR (lifecycle == RUNNING AND lease_expires_at < now)`, sets a new `uuid4()` token, `lease_expires_at = now + lease_seconds`, `attempt_count + 1`. Terminal and awaiting transitions clear `lease_token`/`lease_expires_at`; `complete`/`fail` also clear `pending_resume_payload`. Delete the recovery module and its test (Task 4 removes its use in `main.py`; until then keep `main.py` importing nothing from it — remove `_recover_with_default_session` and the `recover_interrupted_investigations` parameter now, and update `tests/test_main.py` to expect `["open", "setup", "close"]`).

- [ ] **Step 4: Run** the new test file, then `alembic upgrade head` against a scratch SQLite: `DATABASE_URL=sqlite:///./scratch.db .venv/Scripts/python.exe -m alembic upgrade head && rm scratch.db` → succeeds. Existing service/route tests may fail on the changed signatures; they are rewritten in Tasks 3–4.

- [ ] **Step 5: Commit** `Add lease-fenced job transitions to the investigation repository`.

---

### Task 2: Job queue abstraction, SQS implementation, settings

**Files:**
- Create: `apps/api/src/incidentflow/application/jobs/__init__.py`, `apps/api/src/incidentflow/application/jobs/queue.py`
- Create: `apps/api/src/incidentflow/infrastructure/queue/__init__.py`, `apps/api/src/incidentflow/infrastructure/queue/sqs.py`
- Modify: `apps/api/src/incidentflow/core/config.py`, `apps/api/pyproject.toml` (add `"boto3>=1.35,<2.0"`), `apps/api/.env.example`
- Test: `apps/api/tests/test_job_queue.py`

**Interfaces:**
- Produces in `application/jobs/queue.py`:
  - `@dataclass(frozen=True) class ReceivedJob: investigation_id: UUID; receipt: str`
  - `class JobQueue(Protocol)`: `send(investigation_id: UUID) -> None`; `receive(*, max_messages: int, wait_seconds: int) -> list[ReceivedJob]`; `ack(job: ReceivedJob) -> None`; `extend(job: ReceivedJob, *, visibility_seconds: int) -> None`
  - `class InMemoryJobQueue` implementing it; `sent: list[UUID]`, `acked: list[ReceivedJob]` for assertions; `receive` pops in FIFO order and never blocks.
- Produces in `infrastructure/queue/sqs.py`: `class SqsJobQueue(client: Any, queue_url: str)`; `build_job_queue(settings: Settings) -> JobQueue` (boto3 `sqs` client with `endpoint_url=settings.sqs_endpoint_url`, `region_name=settings.job_queue_region`).
- Settings: `job_queue_url: str = "http://localhost:9324/000000000000/incidentflow-investigations"`, `sqs_endpoint_url: str | None = None`, `job_queue_region: str = "us-east-1"`, `worker_concurrency: int = 2`, `job_lease_seconds: int = 300`, `job_max_attempts: int = 3`.

- [ ] **Step 1: Write failing tests:** `test_in_memory_queue_round_trip` (send two ids → receive returns both in order → ack recorded); `test_sqs_queue_uses_expected_requests` with `Stubber` asserting `send_message(QueueUrl, MessageBody='{"investigation_id": "<uuid>"}')`, `receive_message(QueueUrl, MaxNumberOfMessages=2, WaitTimeSeconds=10)` mapped to `ReceivedJob`, `delete_message(ReceiptHandle=...)`, `change_message_visibility(VisibilityTimeout=300)`; `test_sqs_receive_skips_malformed_body` (body `"x"` → acked/deleted and not returned).
- [ ] **Step 2: Run** `pytest tests/test_job_queue.py -q` → FAIL (import error).
- [ ] **Step 3: Implement** the protocol, in-memory queue, SQS queue, settings, dependency; `pip install -e ".[dev]"` in the venv.
- [ ] **Step 4: Run** the test file → PASS; `ruff check src tests scripts` → clean.
- [ ] **Step 5: Commit** `Add the investigation job queue with SQS and in-memory implementations`.

---

### Task 3: Investigation job processor

**Files:**
- Create: `apps/api/src/incidentflow/application/jobs/processor.py`
- Test: `apps/api/tests/test_investigation_job_processor.py`

**Interfaces:**
- Consumes: Task 1 repository methods and `ClaimedInvestigation`.
- Produces:
  - `class JobOutcome(str, Enum): COMPLETED, AWAITING_HUMAN_REVIEW, FAILED, DROPPED`
  - `JIRA_OUTCOME_UNKNOWN_MESSAGE = "The worker stopped while an approved Jira write was being executed. Its outcome is unknown: check Jira before launching a new investigation."`
  - `MAX_ATTEMPTS_MESSAGE = "The investigation could not complete after {attempts} attempts."`
  - `class InvestigationJobProcessor(session_factory: Callable[[], Session], workflow: Any, *, lease_seconds: int, max_attempts: int)`
  - `async process(investigation_id: UUID, *, keep_alive: Callable[[], Awaitable[None]] | None = None) -> JobOutcome`
  - `persist_workflow_result(repository, claimed: ClaimedInvestigation, result: dict) -> Investigation` (moved from `InvestigationService._persist_workflow_result`, now passing `lease_token`).
- `pending_resume_payload` shape (written by Task 4): `{"command_resume": <jira_tool_resume_payload or decision JSON>, "review_event": {"review": ..., "decision": ...}, "review_type": "JIRA_WRITE" | ..., "decision": "APPROVE" | "REJECT" | "REQUEST_INFORMATION"}`.

**Algorithm (`process`):**

```
claimed = repo.claim(id, lease_seconds)            # via asyncio.to_thread
if claimed is None: return DROPPED
if claimed.attempt_count > max_attempts: fail(MAX_ATTEMPTS_MESSAGE); return FAILED
config = {"configurable": {"thread_id": claimed.investigation.workflow_thread_id}}
snapshot = await workflow.aget_state(config)
interrupts = [i for task in snapshot.tasks for i in task.interrupts]
resume = claimed.resume_payload
if not snapshot.values and not snapshot.next:                 # 1. fresh
    run(initial input from the row)
elif interrupts and resume:                                   # 2. resume
    if resume["review_type"] == "JIRA_WRITE" and resume["decision"] == "APPROVE" \
            and claimed.attempt_count > 1:
        fail(JIRA_OUTCOME_UNKNOWN_MESSAGE); return FAILED
    run(Command(resume=resume["command_resume"], update={"review_events": [resume["review_event"]]}))
elif interrupts:                                              # 4. paused, not persisted
    persist({"__interrupt__": interrupts, "report": values.get("report"),
             "human_review": values.get("human_review")})
elif snapshot.next:                                           # 3. continue
    run(None)
else:                                                         # 5. finished, not persisted
    persist(snapshot.values)
```

`run(x)` = `await workflow.ainvoke(x, config)` while a heartbeat task calls `repo.heartbeat` and `keep_alive` every `lease_seconds / 3`; if `heartbeat` returns False the lease was lost: cancel nothing, but skip persistence (fenced writes would no-op anyway) and return `DROPPED`. Any exception from `ainvoke` → `fail("Workflow execution failed before a report was produced.")` → `FAILED`. Map the persisted lifecycle to the `JobOutcome`.

- [ ] **Step 1: Write failing tests** using a real tiny graph on `InMemorySaver` built with `build_investigation_workflow(FakeSupervisor, checkpointer=InMemorySaver())` (reuse the `ApprovalGatedSupervisor` pattern from `test_investigation_api_integration.py`, moved to `tests/agent_fakes.py` if shared):
  - `test_fresh_job_completes` → `COMPLETED`, report persisted.
  - `test_jira_pause_then_resume_completes` → first `process` = `AWAITING_HUMAN_REVIEW`; `request_resume` with an approve payload; second `process` = `COMPLETED`; supervisor saw `{"decisions": [{"type": "approve"}]}`.
  - `test_reclaimed_approved_jira_resume_is_not_rerun` → after `request_resume`, claim once (simulating a dead worker), expire the lease, `process` → `FAILED` with `JIRA_OUTCOME_UNKNOWN_MESSAGE`; the supervisor's resume list is empty.
  - `test_reclaimed_rejected_jira_resume_is_retried` → same with `REJECT` → `COMPLETED`.
  - `test_paused_checkpoint_is_persisted_without_running` (case 4): run the graph directly to its interrupt, then `process` → `AWAITING_HUMAN_REVIEW`, supervisor called exactly once.
  - `test_finished_checkpoint_is_persisted_without_running` (case 5): run the graph to completion directly, then `process` → `COMPLETED`, supervisor called once.
  - `test_max_attempts_fails` → three expired claims, fourth `process` → `FAILED` with `MAX_ATTEMPTS_MESSAGE.format(attempts=3)`.
  - `test_workflow_exception_fails_and_is_not_retried` → throwing supervisor → `FAILED`.
  - `test_unknown_or_terminal_investigation_is_dropped` → random UUID and a `COMPLETED` row → `DROPPED`.
- [ ] **Step 2: Run** `pytest tests/test_investigation_job_processor.py -q` → FAIL.
- [ ] **Step 3: Implement** `processor.py` per the algorithm above.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the crash-safe investigation job processor`.

---

### Task 4: Enqueue from the API (202, 409, DB metrics)

**Files:**
- Modify: `apps/api/src/incidentflow/application/services/investigation_service.py`
- Modify: `apps/api/src/incidentflow/api/routes/investigations.py`, `apps/api/src/incidentflow/main.py`, `apps/api/src/incidentflow/core/operational_metrics.py`
- Modify tests: `tests/test_investigation_service.py`, `tests/test_investigation_routes.py`, `tests/test_investigation_api_integration.py`, `tests/test_main.py`, `tests/test_operational_metrics.py`

**Interfaces:**
- Consumes: Task 1 (`has_active_investigation`, `request_resume`, `count_by_lifecycle`), Task 2 (`JobQueue`, `build_job_queue`), Task 3 (`InvestigationJobProcessor`) in the integration test.
- Produces:
  - `class InvestigationAlreadyActiveError(Exception): investigation_id: UUID`
  - `InvestigationService(repository, incident_repository, queue: JobQueue, workflow: Any)`; `start_investigation(data) -> Investigation | None` (sync, raises `InvestigationAlreadyActiveError`); `request_human_review_resume(investigation_id, decision) -> Investigation | None` (sync; still raises `HumanReviewEditError` before any write); `get_investigation_trace` unchanged.
  - `get_job_queue(request: Request) -> JobQueue` dependency returning `request.app.state.job_queue`; `create_app(..., job_queue_factory: Callable[[Settings], JobQueue] = build_job_queue)`.
  - `/operations/metrics` returns `{"requests_by_status": ..., "investigations_by_lifecycle": repository.count_by_lifecycle()}`; `OperationalMetrics.record_investigation` removed.

- [ ] **Step 1: Write/adjust failing tests:**
  - `test_start_returns_202_pending_and_enqueues_once` (service + route): status 202, `lifecycle == "PENDING"`, `queue.sent == [id]`.
  - `test_start_rejects_active_investigation_with_409`: detail `"An investigation is already running for this incident."`.
  - `test_start_returns_202_when_queue_send_fails`: queue whose `send` raises → 202, row `PENDING`, error logged.
  - `test_resolve_returns_202_and_stores_resume_payload`: payload has the four keys of Task 3's shape; for JIRA_WRITE `command_resume == jira_tool_resume_payload(...)`.
  - `test_second_resolve_is_rejected_with_409`.
  - `test_resolve_with_forbidden_edit_returns_422_and_stays_awaiting`.
  - Integration (rewrite `test_api_resumes_a_manual_supervisor_call_after_jira_hitl`): POST → 202 PENDING; `await processor.process(id)` (use `anyio` via `TestClient` portal or a plain `asyncio.run`); GET → `AWAITING_HUMAN_REVIEW`; resolve → 202; process → GET `COMPLETED`.
  - `test_metrics_count_investigations_from_database`.
- [ ] **Step 2: Run** these files → FAIL.
- [ ] **Step 3: Implement.** Start/resolve/list/get routes become plain `def`; trace stays `async`. Start route: `202` via `status_code=status.HTTP_202_ACCEPTED`. Service commits the row, then `queue.send` inside `try/except Exception: logger.exception(...)`. Lifespan stores `app.state.job_queue = job_queue_factory(settings)` and keeps building the workflow (used only for traces).
- [ ] **Step 4: Run** the full suite `pytest -q` → all pass; `ruff check src tests scripts`.
- [ ] **Step 5: Commit** `Queue investigations from the API and return 202`.

---

### Task 5: Worker process and sweeper

**Files:**
- Create: `apps/api/src/incidentflow/worker.py` (runnable as `python -m incidentflow.worker`)
- Test: `apps/api/tests/test_worker.py`

**Interfaces:**
- Consumes: `JobQueue`, `ReceivedJob` (Task 2); `InvestigationJobProcessor`, `JobOutcome` (Task 3); `stale_investigation_ids` (Task 1).
- Produces:
  - `async run_worker(queue: JobQueue, processor: InvestigationJobProcessor, *, concurrency: int, lease_seconds: int, stop: asyncio.Event, sweep: Callable[[], int] | None = None, sweep_interval_seconds: float = 60, poll_wait_seconds: int = 10) -> None`
  - `sweep_stale_investigations(session_factory, queue: JobQueue, *, pending_older_than_seconds: int = 120) -> int`
  - `async main() -> None`: settings, `open_postgres_checkpointer`, `build_investigation_supervisor`, `build_investigation_workflow`, `build_job_queue`, SIGINT/SIGTERM set `stop` (fall back to `KeyboardInterrupt` on Windows).

Behavior: never more than `concurrency` jobs in flight (`asyncio.Semaphore`); queue calls via `asyncio.to_thread`; `keep_alive` passed to `process` calls `queue.extend(job, visibility_seconds=lease_seconds)`; ack after `process` returns any `JobOutcome`; if `process` raises unexpectedly, log and do **not** ack (SQS redelivers; DLQ after 3). On `stop`, finish in-flight jobs, then return.

- [ ] **Step 1: Write failing tests:** `test_worker_processes_and_acks_each_job` (fake processor, 3 jobs, all acked); `test_worker_respects_concurrency` (fake processor records max simultaneous calls with `concurrency=2` and 5 jobs → max 2); `test_worker_does_not_ack_when_processor_crashes`; `test_worker_stops_after_in_flight_jobs`; `test_sweeper_resends_stale_rows` (SQLite rows: old PENDING + expired RUNNING + fresh PENDING → `queue.sent` has exactly the two stale ids, returns 2).
- [ ] **Step 2: Run** `pytest tests/test_worker.py -q` → FAIL.
- [ ] **Step 3: Implement** `worker.py`.
- [ ] **Step 4: Run** → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `Add the investigation worker with lease heartbeat and sweeper`.

---

### Task 6: Local stack (ElasticMQ + worker service)

**Files:**
- Create: `infra/elasticmq/elasticmq.conf`
- Modify: `docker-compose.yml`, `apps/web/nginx.conf`, `apps/api/.env.example`, `docs/docker-local.md`, `CLAUDE.md` (Commands + pipeline steps 1–2)

Details: `elasticmq` service image `softwaremill/elasticmq-native` pinned to an exact release tag (check Docker Hub; never `latest`), port `127.0.0.1:9324:9324`, config mounted read-only, queues `incidentflow-investigations` (`defaultVisibilityTimeout = 300 seconds`, `deadLettersQueue { name = "incidentflow-investigations-dlq", maxReceiveCount = 3 }`) and the DLQ. `api` and new `worker` services get `JOB_QUEUE_URL=http://elasticmq:9324/000000000000/incidentflow-investigations`, `SQS_ENDPOINT_URL=http://elasticmq:9324`, dummy `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (`local`). `worker` reuses the `api` build, env and volumes, `command: ["python", "-m", "incidentflow.worker"]`, depends on `migrate` (completed) and `elasticmq` (started); no ports. nginx `/api/` location drops `proxy_read_timeout 300s` and its comment.

- [ ] **Step 1: Run** `docker compose config -q` from the repo root → exit 0.
- [ ] **Step 2 (if Docker is running): Smoke test** `docker compose up --build -d`, create an incident and start an investigation through `http://127.0.0.1:5173`; `POST` returns 202 and `docker compose logs worker` shows the job claimed and finished. If Docker is unavailable, say so in the task report.
- [ ] **Step 3: Commit** `Run investigations in a worker service backed by ElasticMQ`.

---

### Task 7: Dashboard follows queued investigations

**Files:**
- Modify: `apps/web/src/hooks/useIncidentFlow.ts`, `apps/web/src/api.ts`, the investigation status display (where lifecycle labels render: `pages/InvestigationsPage.tsx` / `features/investigations/*`)
- Test: `apps/web/src/hooks/useIncidentFlow.test.ts` (new) or the existing page tests

Behavior: `startInvestigation` posts, selects the returned `PENDING` investigation immediately, sets status `"Investigation queued…"`, and removes its temporary 1.5 s poller; the existing workspace polling refreshes it, and the status line becomes `"Investigation running…"`, then the existing completed/paused/failed messages when the selected investigation's lifecycle changes. `request` in `api.ts` attaches `status` to the thrown error (`class ApiError extends Error { status: number }`); on 409 the hook refreshes investigations, selects the incident's `PENDING`/`RUNNING` one, and shows `"An investigation is already running for this incident."`. `resolveHumanReview` likewise accepts the `PENDING` response. `PENDING` gets a visible "Queued" label.

- [ ] **Step 1: Write failing tests** (vitest + mocked `fetch`): start shows "Investigation queued…" and selects the PENDING item; 409 selects the active investigation and shows the message.
- [ ] **Step 2: Run** `npm test` in `apps/web` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm run lint && npm test && npm run build` → all succeed.
- [ ] **Step 5: Commit** `Show queued and running investigations in the dashboard`.

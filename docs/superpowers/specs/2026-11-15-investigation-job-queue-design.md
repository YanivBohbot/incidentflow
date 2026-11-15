# Investigation job queue and workers

## Intent

Today an investigation runs inside the HTTP request that starts it
(`InvestigationService.run_investigation` awaits `workflow.ainvoke`). A run takes minutes, so:

- proxies time out (nginx was already raised to 300 s) while the backend keeps running, and the
  operator retries, creating duplicate investigations;
- every restart or deploy kills in-flight investigations (`recover_interrupted_investigations`
  fails every `RUNNING` row at startup);
- two API instances corrupt state: one instance's startup recovery fails the other's running
  investigation, and `complete_investigation` later flips it back to `COMPLETED` without
  checking the current lifecycle;
- there is no back-pressure: N simultaneous incidents run N workflows, with their MCP
  subprocesses and LLM calls, inside the API process.

This step decouples **accepting** an investigation from **executing** it. The API records the
request and puts a job on a queue; separate workers execute the unchanged LangGraph workflow. It
is the foundation for two later steps: deploying serverless on AWS (Lambda + SQS) and event
ingestion (CloudWatch alarms creating incidents and jobs automatically).

## Decisions already made (by the owner)

- Target platform is the owner's AWS account, serverless, with a budget of about $10/month:
  SQS as the job queue, Lambda workers, Postgres on a free managed provider (Neon). **This step
  is local only**; AWS deployment is a separate, later step.
- Event ingestion comes after this step and will enqueue jobs through the same path.
- Auth/RBAC is parked; nothing here depends on it.

## Goals

- `POST /api/investigations` and `POST /api/investigations/{id}/human-review/resolve` return
  `202 Accepted` immediately with the investigation in `PENDING`; execution happens in a worker.
- A worker crash, restart, or deploy never loses an investigation: another worker reclaims the
  job and continues from the last durable checkpoint.
- Several workers and several API instances can run at the same time without double execution
  or contradictory lifecycle states.
- A bounded number of investigations run concurrently; the rest wait in the queue.
- The same job-processing code runs locally (docker compose) and, later, in a Lambda handler.
- The dashboard shows queued and running investigations and follows them live, as it does now.

## Non-goals

- No AWS resources, IaC, or Lambda handler in this step (next step).
- No event ingestion, deduplication of alerts, or trigger rules (later step).
- No change to the agents, prompts, MCP clients, guardrails, or human-review policies.
- No SSE/WebSocket streaming; the dashboard keeps polling.
- No auth or RBAC.

## Anti-goals (would make this a failure even if it works)

- An approved Jira write executed twice because a job was retried. The existing rule stands:
  **no automatic retry of an external write whose outcome is unknown.**
- A job silently stuck forever in `PENDING` or `RUNNING` with nothing to recover it.
- Local development or the test suite now needing AWS credentials or internet access.

## Design

### Lifecycle and job ownership

`InvestigationLifecycle` keeps its values. `PENDING` now means "queued, not yet claimed".

```
POST start   → PENDING ──claim──▶ RUNNING ──▶ COMPLETED | FAILED | AWAITING_HUMAN_REVIEW
POST resolve → AWAITING_HUMAN_REVIEW ──▶ PENDING ──claim──▶ RUNNING ──▶ ...
```

The investigation row in Postgres is the source of truth; the queue message only says "look at
investigation X". New columns on `investigations` (one Alembic revision):

- `lease_expires_at` (timestamptz, nullable): set on claim, extended by heartbeat.
- `attempt_count` (int, default 0): incremented on each claim.
- `pending_resume_payload` (JSON, nullable): the validated resume payload stored by the resolve
  endpoint, consumed by the worker.

Every lifecycle transition becomes a **conditional update** (`UPDATE … WHERE id = :id AND
lifecycle = :expected …`) that reports whether it applied. `complete_investigation`,
`fail_investigation`, and `mark_awaiting_human_review` only apply to a `RUNNING` row owned by the
current claim; a stale worker's late write is ignored.

**Claim rule:** a worker may claim a row that is `PENDING`, or `RUNNING` with
`lease_expires_at < now()` (its previous worker died). Claim sets `RUNNING`, a new lease, and
`attempt_count + 1`, atomically. If the claim does not apply, the message is a duplicate or stale:
acknowledge and drop it.

**Attempts:** if `attempt_count` would exceed `JOB_MAX_ATTEMPTS` (default 3), the worker marks the
investigation `FAILED` ("could not complete after 3 attempts") instead of running it.

### What the worker runs: derived from the checkpoint, not the message

So that a job can be retried safely at any point, the worker decides what to do from the
checkpoint state of `workflow_thread_id`:

1. No checkpoint yet → `ainvoke(initial input)` (same input as today).
2. A pending interrupt and `pending_resume_payload` is set → `ainvoke(Command(resume=…,
   update={"review_events": […]}))`, exactly as `resume_human_review` does today.
3. Checkpoint with pending next nodes and no interrupt → `ainvoke(None, config)` to continue
   from the last checkpoint.
4. A pending interrupt but no `pending_resume_payload` → the previous worker reached the pause
   but died before persisting it. Do not run anything; persist `AWAITING_HUMAN_REVIEW` from the
   interrupt value in the snapshot, through the same conversion as today
   (`jira_write_review_from_interrupt` or the report-level review).
5. A checkpoint with no next nodes → the graph already finished but the previous worker died
   before persisting the result. Do not run anything; persist from the checkpoint's values.

The result is persisted with the existing `_persist_workflow_result` logic, which moves from the
request path into the worker.

**Jira write safety:** `attempt_count` is reset to 0 when the resolve endpoint re-queues an
investigation, so it counts the attempts of the current job only. If a job resuming an approved
`JIRA_WRITE` review is claimed with `attempt_count > 1`, the worker must not resume it: a crash
after the Jira call but before the next checkpoint is indistinguishable from a crash before the
call. It marks the investigation `FAILED` with a message telling the operator the Jira write
outcome is unknown and to check Jira. This is deliberately conservative (a crash before the call
also ends here). Rejections and report-level reviews have no external write and are retried
normally; read-only work is always safe to re-run.

### Queue abstraction

A small `JobQueue` interface in `application/` (send a job, receive jobs, acknowledge, extend
visibility), with two implementations:

- `SqsJobQueue` (boto3). Locally it targets **ElasticMQ**, an SQS-compatible container, through
  `SQS_ENDPOINT_URL`; on AWS the same code targets real SQS. It is the only production
  implementation, so local and AWS behave the same.
- `InMemoryJobQueue` for tests.

Message body: `{"investigation_id": "<uuid>"}`. Delivery is at-least-once, so duplicates are
expected and handled by the claim rule.

### API changes

- `POST /investigations`: validate the incident exists (404), **reject with 409 if the incident
  already has a `PENDING` or `RUNNING` investigation** (the double-click/retry duplicate), create
  the row in `PENDING`, commit, send the message, return `202` with the investigation.
- `POST /{id}/human-review/resolve`: keep today's synchronous validation (409 if not awaiting
  review, 422 for an edit outside the permitted Jira fields via `jira_tool_resume_payload`), store
  the payload in `pending_resume_payload`, move `AWAITING_HUMAN_REVIEW → PENDING`, commit, send,
  return `202`.
- If sending the message fails after the commit, the row stays `PENDING` and the sweeper (below)
  re-sends it; the API still returns `202`.
- Routes that only touch the database become plain `def` (FastAPI runs them in its threadpool) so
  synchronous SQLAlchemy no longer blocks the event loop. The trace endpoint stays `async` and
  keeps reading checkpoints through the lifespan-owned compiled workflow; the API still builds the
  workflow and checkpointer but never executes it.
- `recover_interrupted_investigations` (fail every `RUNNING` at startup) is removed; leases replace
  it.
- `/operations/metrics` computes `investigations_by_lifecycle` from a database count instead of an
  in-process counter, so it is correct with separate worker processes.

### Worker process

A new entry point, `python -m incidentflow.worker`, using the same image and settings:

- opens the Postgres checkpointer and builds the workflow once at startup (as `main.lifespan` does);
- receives messages and runs up to `WORKER_CONCURRENCY` jobs at once (default 2);
- while a job runs, heartbeats every `JOB_LEASE_SECONDS / 3`: extends `lease_expires_at` and the
  message visibility timeout;
- acknowledges (deletes) the message after the result is persisted, or after deciding to drop it;
- runs a **sweeper** every minute: re-sends a message for `PENDING` rows not updated for more than
  2 minutes, and for `RUNNING` rows whose lease has expired. This covers a lost message and a
  crash between commit and send. Duplicates are harmless because of the claim rule.

The per-job function (`process_investigation_job(investigation_id)`) contains all the logic; the
loop is a thin driver around it, so a Lambda handler can call the same function in the next step.

### Local stack

`docker-compose.yml` gains an `elasticmq` service (queue created at startup, with a dead-letter
queue after 3 receives) and a `worker` service built from `apps/api`, which depends on `migrate`
and `elasticmq`. The `api` service gets the queue settings. nginx's 300 s `proxy_read_timeout`
goes back to a normal value since no request waits for a run.

New settings in `core/config.py`: `JOB_QUEUE_URL`, `SQS_ENDPOINT_URL` (unset on AWS),
`AWS_REGION` for the queue client, `WORKER_CONCURRENCY`, `JOB_LEASE_SECONDS` (default 300),
`JOB_MAX_ATTEMPTS` (default 3). New dependency: `boto3`.

### Dashboard

`startInvestigation` and `resolveHumanReview` receive a `PENDING` investigation right away,
select it, and rely on polling until it reaches `COMPLETED`, `FAILED`, or
`AWAITING_HUMAN_REVIEW`. The status line shows "Queued…" then "Running…". The temporary poller
in `startInvestigation` that hunts for the `RUNNING` row is no longer needed. A 409 on start shows
"An investigation is already running for this incident" and selects it.

## Testing

No live services, as today: SQLite repositories, `InMemorySaver`, `InMemoryJobQueue`, fake
workflows. Required behaviors:

- start and resolve return 202 with `PENDING`, and enqueue exactly one message;
- a second start for an incident with an active investigation returns 409;
- claim applies once; a duplicate message for a claimed row is dropped;
- a `RUNNING` row with an expired lease is reclaimed, and the stale worker's late completion is
  ignored;
- the worker picks the right action from the checkpoint (fresh start, resume, continue), using a
  small real graph on `InMemorySaver`, including a pause that was checkpointed but never
  persisted (case 4);
- a reclaimed resume of an approved Jira write is not re-run and ends `FAILED` with the
  "outcome unknown" message;
- `JOB_MAX_ATTEMPTS` is enforced;
- the sweeper re-sends stale `PENDING` and expired `RUNNING` rows;
- web: the start flow handles a `PENDING` response and the 409.

Conditional updates using `SKIP LOCKED` or `RETURNING` are not needed; a plain conditional
`UPDATE` with a row count works on both SQLite and Postgres.

## Left to the builder

- Module layout for the queue and the worker, and naming.
- Whether the worker loop uses threads or asyncio for concurrency (the workflow is async; the
  repositories are synchronous and may be called through `asyncio.to_thread`).
- Exact heartbeat, poll interval, and sweeper thresholds within the values above.
- How the dashboard words the queued/running states.

## Calls I made (owner can override)

- ElasticMQ locally rather than LocalStack: lighter, and SQS is the only AWS service needed here.
- The investigation row doubles as the job record; no separate `jobs` table.
- 409 on a duplicate start rather than returning the existing investigation silently.
- Metrics for investigations come from the database.

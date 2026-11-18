# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

IncidentFlow is an AI incident-investigation platform: a FastAPI API (`apps/api`) that runs a
LangGraph/LangChain multi-agent workflow over Jira, MongoDB, Pinecone, GitHub, and AWS CloudWatch
(via MCP), plus a React + Vite dashboard (`apps/web`).

## Commands

API (run from `apps/api`, Python 3.12 or 3.13):

```powershell
pip install -e ".[dev,eval]"
uvicorn incidentflow.main:app --reload        # needs DATABASE_URL + OPENAI_API_KEY in apps/api/.env
python -m incidentflow.worker                 # runs queued investigations; needs a queue (see below)
pytest -q                                     # full suite (CI sets LANGSMITH_TRACING=false)
pytest tests/test_investigation_workflow.py   # one file
pytest tests/test_investigation_workflow.py::test_<name>   # one test
ruff check src tests scripts evaluation       # CI lints scripts/ and evaluation/ too
ruff format --check src tests evaluation
alembic upgrade head
alembic revision -m "add_incident_assignee"   # name revisions after the change
python -m evaluation.run --suite all          # LangSmith experiments (real OpenAI + LangSmith)
python -m evaluation.upload_evaluators        # upload code evaluators to the datasets
python -m evaluation.summary                  # write docs/evaluation.md
```

`apps/api/evaluation/` is the LangSmith evaluation package (see its README); the three
`evaluation.*` commands call real OpenAI/LangSmith and are not part of `pytest`.

Web (run from `apps/web`, Node 22): `npm ci`, `npm run dev`, `npm run lint` (oxlint),
`npm run build` (`tsc -b && vite build`). The Vite dev server proxies `/api`, `/health`, and
`/operations` to `http://127.0.0.1:8000`.

Full local stack (from repo root): copy `.env.example` → `.env` and `apps/api/.env.example` →
`apps/api/.env`, then `docker compose up --build -d`. This runs postgres → one-shot `migrate`
(alembic) → `api` + `worker` (with ElasticMQ, an SQS-compatible queue on 9324) → `web` (nginx
proxies `/api/*`), plus Keycloak on 8080. To run the API/worker on the host against a compose
queue, set `SQS_ENDPOINT_URL=http://127.0.0.1:9324` and the host `JOB_QUEUE_URL` (the queue
client brings its own dummy credentials; never export `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`,
they override the CloudWatch MCP profile). See
`docs/docker-local.md`. Never use `docker compose down --volumes` unless you intend to delete the
database and persisted LangGraph checkpoints.

CI (`.github/workflows/ci.yml`) runs ruff check + pytest for the API and lint + build for the web.

## Architecture

### Layering (API)

`api/routes/` → `application/services/` → `infrastructure/database/` repositories (SQLAlchemy).
Pydantic request/response contracts live in `domain/<area>/models.py`; ORM models are in
`infrastructure/database/models.py`. Routers build services through FastAPI dependencies
(`get_investigation_service`, etc.) — tests override these dependencies rather than patching.
Settings come from `core/config.py` (`get_settings()` is `lru_cache`d; tests set env vars with
`monkeypatch` and call `get_settings.cache_clear()`).

### Investigation pipeline (the part that spans many files)

1. `main.create_app()` lifespan opens an `AsyncPostgresSaver` checkpointer
   (`agent/orchestration/checkpoints/postgres.py`, uses `LANGGRAPH_CHECKPOINT_DATABASE_URL` or
   falls back to `DATABASE_URL`), builds the supervisor, and stores the compiled workflow on
   `app.state.investigation_workflow`. `/health/ready` reports whether this has happened.
2. Start/resume requests persist an investigation row as `PENDING`, send
   `{"investigation_id"}` to the SQS-compatible job queue (`JOB_QUEUE_URL`; ElasticMQ locally,
   dead-letter after 3 receives), and return 202. The separate worker process
   (`python -m incidentflow.worker`, `WORKER_CONCURRENCY`) claims the row with a lease
   (`JOB_LEASE_SECONDS`, `JOB_MAX_ATTEMPTS`, run deadline `JOB_TIMEOUT_SECONDS`), then calls
   `workflow.ainvoke(..., thread_id=investigation.workflow_thread_id)`; a sweeper re-sends stale
   rows. The DB row is the product lifecycle (`InvestigationLifecycle`: `PENDING` → `RUNNING` →
   `AWAITING_HUMAN_REVIEW` / `COMPLETED` / `FAILED`); the checkpointer holds graph state for resume.
3. `agent/orchestration/investigation_workflow.py` is an explicit `StateGraph`:
   `validate → prepare → investigate → capture_report → (review) → finalize | fail`. The
   `investigate` node has a retry policy and an error handler from `fault_tolerance/`.
4. The supervisor (`agent/orchestration/supervisor.py`) is a `create_agent` whose tools are the
   five specialist delegations in `agent/tools/*_tools.py` (`ask_it_operations` = Jira,
   `ask_data_intelligence` = MongoDB, `ask_knowledge` = Pinecone, `ask_github`,
   `ask_cloudwatch` = AWS CloudWatch via the AWS Labs MCP server over stdio/uv). It returns a
   structured `InvestigationReport` via `ToolStrategy`. Middleware bounds tool selection, retries
   only read delegations, and caps calls per tool.
5. Each delegation tool opens an MCP client (`agent/mcp_clients/`), builds a specialist agent
   (`agent/agents_specialist/`) with a structured finding (`agent/findings/`), and returns the
   finding as JSON. When an integration's `*_ENABLED` flag is false or it fails, the tool returns a zero-confidence placeholder finding instead of raising — except `GraphInterrupt`,
   which must propagate.

### Human review (two distinct pause points)

- **Report-level review**: `capture_report` uses `policies/human_review.accepted_human_review` to
  decide whether to `interrupt()` in the `review` node.
- **Jira writes**: the Jira specialist's `HumanInTheLoopMiddleware` interrupts inside the nested
  agent before `createJiraIssue` / `addOrEditJiraIssueComment`. The service detects this via
  `__interrupt__` and converts it with `jira_write_review_from_interrupt`.

`POST /api/investigations/{id}/human-review/resolve` resumes with `Command(resume=...)` on the same
thread; for Jira-write reviews the payload is translated by `jira_tool_resume_payload`. Specialist
tools receive the parent `RunnableConfig` so nested interrupts checkpoint on the parent thread.

### Guardrails and integration constraints

- `agent/middleware.build_shared_middleware()` wraps every tool result as untrusted external
  evidence (`agent/guardrails/external_evidence.py`); every agent includes it.
- MCP clients expose only allowlisted tools (e.g. `JIRA_READ_TOOL_NAMES` /
  `JIRA_WRITE_TOOL_NAMES`). GitHub calls are restricted to `GITHUB_MCP_REPOSITORIES` by
  `GitHubRepositoryAllowlistMiddleware`; GitHub MCP runs read-only (stdio via Docker by default).
- Pinecone is read-only at runtime; indexes are populated by explicit scripts
  (`scripts/ingest_*.py`). Resolved-incident "memory" is written only through the operator-confirmed
  `POST /api/investigations/{id}/memory-lessons` endpoint, gated by
  `PINECONE_RESOLVED_INCIDENTS_ENABLED`.
- Jira MCP uses OAuth; tokens can be cached encrypted under `MCP_OAUTH_TOKEN_STORE_DIR`.

### Tests

Tests do not need live services: repositories use in-memory SQLite (`Base.metadata.create_all`),
workflow tests use `InMemorySaver`, and service/route tests inject fake workflow objects with an
`ainvoke` method. Async tests use `@pytest.mark.anyio`. `apps/api/scripts/` holds manual
run/verify/evaluate scripts that hit real integrations — they are not part of the test suite.
`evaluation/tests/` holds offline tests of the evaluation code (collected by `pytest`); the
experiments themselves (`python -m evaluation.run`) hit real OpenAI/LangSmith and never run in pytest.

## Conventions

The parent `AGENTS.md` (one directory up) defines the coding/testing/PR rules: 100-char Ruff line
limit, type annotations, `test_<behavior>` names, no persistence logic in routers, concise
imperative commit subjects, and a `Co-Authored-By:` trailer on AI-authored commits. Design specs and
implementation plans for recent features are in `docs/superpowers/`.

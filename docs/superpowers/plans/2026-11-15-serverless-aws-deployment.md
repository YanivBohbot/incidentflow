# Serverless AWS Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy IncidentFlow on the owner's AWS account (Lambda + SQS + API Gateway + S3/CloudFront +
Cognito, Neon Postgres, MongoDB Atlas) from GitHub Actions, with all five integrations working and
Cognito sign-in, while local docker compose keeps working.

**Architecture:** One container image from `apps/api` serves four Lambdas (api via Lambda Web
Adapter, worker on SQS, sweeper on a schedule, migrate on demand). The worker calls the existing
`InvestigationJobProcessor`. A Python CDK app in `infra/cdk/` describes everything; `deploy.yml`
pushes the image, deploys, migrates, and publishes the dashboard.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, LangGraph, fastmcp 4.1.3, py-key-value-aio 0.4.6
(`disk`, `dynamodb` extras), PyJWT, awslambdaric, AWS Lambda Web Adapter, AWS CDK v2 (Python),
React 19 + Vite + `oidc-client-ts`, GitHub Actions with OIDC.

**Spec:** `docs/superpowers/specs/2026-11-15-serverless-aws-deployment-design.md`

## Global Constraints

- Branch `feature/serverless-aws-deployment`, stacked on `feature/investigation-job-queue`. Never
  stage `.vscode/settings.json` or `CLAUDE.md`.
- Region `us-east-1`. Lambdas are **not in a VPC**; no NAT gateway, no RDS, no Secrets Manager, no
  provisioned concurrency.
- Secrets only in SSM SecureString under `/incidentflow/`; never in the repo, image, plain Lambda
  env values, GitHub, or logs. The owner's email is never committed.
- Worker Lambda: timeout 900 s, SQS batch size 1, event-source maximum concurrency 2,
  `JOB_TIMEOUT_SECONDS=780`, queue visibility timeout ≥ 900 s, DLQ after 3 receives.
- Sweeper schedule: every 15 minutes.
- Log retention 14 days on every log group. AWS Budget $10/month, alerts at 50/80/100 %.
- Images and Lambdas are x86_64.
- Tests need no AWS and no internet (`pytest -q` in `apps/api`, `npm test` in `apps/web`,
  `pytest` in `infra/cdk`). Local compose behaviour unchanged when the new settings are unset:
  `AUTH_ENABLED=false`, `MONGODB_MCP_TRANSPORT=http`, `MCP_OAUTH_TOKEN_STORE=disk`.
- Neon: pooled URL for SQLAlchemy (API, worker, sweeper) with `NullPool`; direct URL in
  `LANGGRAPH_CHECKPOINT_DATABASE_URL` for the checkpointer and migrations.
- Cognito access token: verify issuer, `client_id`, `token_use == "access"`, signature, expiry;
  groups from `cognito:groups`; actor = `cognito:username`. Roles: `viewer`, `operator`. No
  separation-of-duties check.
- Ruff line length 100, type annotations, `test_<behavior>` names, concise imperative commit
  subjects ending with the session's `Co-Authored-By:` trailer.

## Review Focus

1. **Neon waking from suspend** at an API cold start must delay, not fail: the engine uses a
   connect timeout of at least 15 s (Task 3 test).
2. **Missing, expired, wrong-client, or group-less tokens** must give 401/403 with a JSON
   `detail`, never 500; an unreachable JWKS endpoint gives 503 (Task 6 tests).
3. **A malformed SQS message body** must be acknowledged and logged, not redelivered until the
   DLQ (Task 5 test).
4. **The first deploy before the Jira authorization script ran** (empty token table) must yield a
   zero-confidence Jira finding within seconds, never a 300 s wait (Task 1 test with a 5 s
   bound).
5. **A warm Lambda reused for a second message** must reuse its event loop and workflow without
   "Event loop is closed" or a second checkpointer setup (Task 5 test).

---

### Task 1: Durable, non-interactive Jira token store

**Files:**
- Create: `apps/api/src/incidentflow/agent/mcp_clients/oauth_store.py`
- Modify: `apps/api/src/incidentflow/agent/mcp_clients/jira.py` (`_oauth_auth`)
- Modify: `apps/api/src/incidentflow/core/config.py`, `apps/api/pyproject.toml`
  (`py-key-value-aio[disk,dynamodb]`), `apps/api/.env.example`
- Modify: the Jira delegation tool that builds the zero-confidence finding (find it from
  `agent/tools/it_operations_tools.py` or wherever `JiraMCPClient` is used) so
  `JiraAuthorizationRequiredError` is reported in the finding's limitation text
- Test: `apps/api/tests/test_jira_oauth_store.py`

**Interfaces:**
- Produces settings: `mcp_oauth_token_store: Literal["disk", "dynamodb"] = "disk"`,
  `mcp_oauth_dynamodb_table: str | None = None`, `mcp_oauth_interactive: bool = False`
  (keeps `mcp_oauth_token_store_dir`, `mcp_oauth_storage_encryption_key`).
- Produces `class JiraAuthorizationRequiredError(RuntimeError)` with the message
  `"Jira authorization expired or missing; run scripts/authorize_jira.py."`
- Produces `build_oauth_token_storage(settings: Settings) -> AsyncKeyValue | None` (`None` means
  neither store setting is configured → today's plain `"oauth"` behaviour), always wrapped in
  `FernetEncryptionWrapper` when it returns a store.
- Produces `class NonInteractiveOAuth(fastmcp.client.auth.OAuth)` whose `redirect_handler` raises
  `JiraAuthorizationRequiredError` before any network call or browser, and whose
  `callback_handler` raises the same (never starts the callback server).
- `JiraMCPClient(server_url: str, *, interactive: bool | None = None)`; `None` means
  `settings.mcp_oauth_interactive`. Interactive → plain `OAuth`; otherwise `NonInteractiveOAuth`.

- [ ] **Step 1: Write failing tests**
  - `test_dynamodb_store_selected_when_configured`: settings with `MCP_OAUTH_TOKEN_STORE=dynamodb`,
    `MCP_OAUTH_DYNAMODB_TABLE=t`, a Fernet key → returned object is a `FernetEncryptionWrapper`
    whose inner store is `DynamoDBStore` (construct it with `auto_create=False`; no AWS call at
    construction).
  - `test_disk_store_requires_both_settings`: dir without key raises the existing `RuntimeError`.
  - `test_non_interactive_oauth_fails_fast_without_tokens`: `NonInteractiveOAuth` over a
    `MemoryStore`; awaiting `redirect_handler("https://example.invalid/authorize")` raises
    `JiraAuthorizationRequiredError`; `callback_handler()` raises it too.
  - `test_jira_finding_reports_reauthorization_within_bound`: the Jira delegation tool with a
    `JiraMCPClient` whose `read_tools()` raises `JiraAuthorizationRequiredError` returns a
    zero-confidence finding mentioning `authorize_jira.py`, under `asyncio.timeout(5)`.
- [ ] **Step 2: Run** `pytest tests/test_jira_oauth_store.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `oauth_store.py` and wire `_oauth_auth`. The DynamoDB store uses the
  region from `AWS_REGION` (or `job_queue_region`) and `auto_create=False` (CDK owns the table).
  `_oauth_auth` passes `callback_port` only when interactive.
- [ ] **Step 4: Run** `pytest -q` → all pass; `ruff check src tests scripts` clean.
- [ ] **Step 5: Create `apps/api/scripts/authorize_jira.py`**: forces
  `JiraMCPClient(settings.jira_mcp_url, interactive=True)`, runs the same read checks as
  `verify_jira_read_access.py` (import its helpers), prints which store received the state.
  Add `scripts/check_jira_refresh.py`: opens the configured store, sets the stored token expiry
  (`TokenStorageAdapter` expiry key) to the past, then runs the read verification with
  `interactive=False` and prints `Refresh succeeded` or the exception class.
- [ ] **Step 6: Commit** `Store Jira OAuth state durably and fail fast without it`.

### Task 2: Gate — prove a refresh works away from the authorizing process (with the owner)

No code. The controller runs this with the owner and records the result in the ledger.

- [ ] **Step 1:** Owner runs `python scripts/authorize_jira.py` on the host with the disk store
  (existing `.env`).
- [ ] **Step 2:** Copy (not bind-mount) the token-store directory into a fresh container built from
  `apps/api` (`docker cp` into `/tmp/jira-store`), set `MCP_OAUTH_TOKEN_STORE_DIR=/tmp/jira-store`,
  and run `python scripts/check_jira_refresh.py` inside it.
- [ ] **Step 3:** Expected `Refresh succeeded`. If it fails because the refresh token or client
  registration is bound to the original process/redirect, **stop the plan** and bring the Jira
  design back to the owner (spec, "Answers to the builder check").

### Task 3: Cloud settings — SSM secrets, Neon pooling, region fallback

**Files:**
- Create: `apps/api/src/incidentflow/core/ssm.py`
- Modify: `apps/api/src/incidentflow/core/config.py`,
  `apps/api/src/incidentflow/infrastructure/database/session.py`
- Test: `apps/api/tests/test_cloud_settings.py`

**Interfaces:**
- Produces `load_ssm_parameters_into_environ(path: str, *, client: Any | None = None) -> list[str]`:
  `GetParametersByPath(Path=path, Recursive=False, WithDecryption=True)` with pagination; parameter
  `/incidentflow/OPENAI_API_KEY` → env var `OPENAI_API_KEY`; an env var already set wins; returns
  the names it set (names only — never log values). Called by the Lambda entry points (Task 5)
  when `INCIDENTFLOW_SSM_PATH` is set, before `get_settings()`.
- Settings: `database_null_pool: bool = False`, `database_connect_timeout_seconds: int = 15`;
  `job_queue_region: str | None = None` with a property `queue_region` returning
  `job_queue_region or os.environ.get("AWS_REGION") or "us-east-1"` (update `build_job_queue`).
- `get_session_factory()` builds the engine with `NullPool` when `database_null_pool`, and
  `connect_args={"connect_timeout": database_connect_timeout_seconds, "prepare_threshold": None}`
  for PostgreSQL URLs only (SQLite tests unaffected).

- [ ] **Step 1: Write failing tests**: `test_ssm_parameters_fill_missing_environment` (fake client
  with two pages; preset var not overwritten; returned names), `test_queue_region_falls_back_to_aws_region`,
  `test_postgres_engine_uses_null_pool_and_connect_timeout` (inspect `engine.pool` class and the
  dialect's connect args via `engine.url`/`create_engine` patch), `test_sqlite_engine_has_no_postgres_connect_args`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest -q` → PASS.
- [ ] **Step 5: Commit** `Load secrets from SSM and tune database connections for Neon`.

### Task 4: Job-queue follow-ups for many API instances

**Files:**
- Create: `apps/api/alembic/versions/<rev>_unique_active_investigation.py` (down_revision
  `f1a2b3c4d5e6`), `apps/api/src/incidentflow/migrate.py`
- Modify: `infrastructure/database/models.py`, `investigation_repository.py`,
  `application/services/investigation_service.py`, `application/jobs/processor.py`,
  `main.py`, `worker.py`, `docker-compose.yml` (`migrate` command)
- Test: `tests/test_investigation_job_repository.py`, `tests/test_investigation_service.py`,
  `tests/test_investigation_job_processor.py`, `tests/test_migrate.py`

**Interfaces:**
- Partial unique index `uq_investigations_active_incident` on `investigations(incident_id)` where
  `lifecycle IN ('PENDING','RUNNING')` (`postgresql_where` and `sqlite_where`). The service turns
  the resulting `IntegrityError` on create into `InvestigationAlreadyActiveError` (existing 409).
  Note: `request_resume` moves `AWAITING_HUMAN_REVIEW → PENDING` for the same row and never
  conflicts with itself.
- Repository time: `_database_now(session) -> datetime` (aware UTC) from
  `select(func.now(type_=DateTime(timezone=True)))`, used when `now` is not passed (tests keep
  passing `now`). SQLite returns a naive value; attach UTC.
- Processor: call `keep_alive` once immediately after a successful claim, before running.
- `incidentflow.migrate.run_migrations() -> None`: `alembic upgrade head` via `alembic.command`
  with the packaged `alembic.ini`, then `checkpointer.setup()` on `checkpoint_database_url`.
  `python -m incidentflow.migrate` runs it. Remove `checkpointer.setup()` from `main.lifespan`
  and `worker.main`; compose `migrate` runs `python -m incidentflow.migrate`.

- [ ] **Step 1: Failing tests**: `test_second_active_investigation_violates_unique_index`,
  `test_concurrent_start_maps_integrity_error_to_already_active`,
  `test_completed_investigation_allows_a_new_one`, `test_keep_alive_called_right_after_claim`,
  `test_claim_uses_database_time_when_now_omitted` (SQLite), `test_migrate_runs_alembic_then_checkpointer_setup`
  (patch `alembic.command.upgrade` and a fake checkpointer context).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `pytest -q` → PASS; also
  `alembic upgrade head` against the compose Postgres (`docker compose up -d postgres`) succeeds.
- [ ] **Step 5: Commit** `Guard active investigations with a unique index and move setup to migrate`.

### Task 5: Lambda entry points

**Files:**
- Create: `apps/api/src/incidentflow/lambda_handlers.py`
- Test: `apps/api/tests/test_lambda_handlers.py`

**Interfaces:**
- Consumes `InvestigationJobProcessor.process(id, *, keep_alive) -> JobOutcome`,
  `ReceivedJob(investigation_id: UUID, receipt: str)`, `JobQueue.extend`,
  `sweep_stale_investigations`, `build_processor`, `run_migrations`,
  `load_ssm_parameters_into_environ`.
- Produces `worker_handler(event: dict, context: Any) -> dict` returning
  `{"batchItemFailures": [{"itemIdentifier": messageId}, ...]}`; `sweeper_handler(event, context)
  -> dict` returning `{"resent": n}`; `migrate_handler(event, context) -> dict` returning
  `{"status": "migrated"}`.
- One module-level runtime per execution environment: a persistent event loop
  (`asyncio.new_event_loop()`, reused via `run_until_complete`), and, on first worker use, an
  entered `AsyncExitStack` holding the checkpointer and the built workflow and processor.
  Builders are injectable (module-level factory functions tests can replace) so tests use
  `InMemorySaver` and a fake processor.
- Record handling: body JSON `{"investigation_id"}`; malformed body or bad UUID → log and treat
  as success (no failure item). `process()` returning any outcome → success. `process()`
  raising → failure item. `keep_alive` calls `queue.extend(ReceivedJob(id, receiptHandle),
  visibility_seconds=settings.job_lease_seconds)` via `asyncio.to_thread`, swallowing errors as
  the local worker does.

- [ ] **Step 1: Failing tests**: `test_worker_handler_reports_only_crashed_records`,
  `test_worker_handler_acknowledges_malformed_body`, `test_keep_alive_extends_with_receipt_handle`,
  `test_warm_invocation_reuses_loop_and_workflow` (call twice; builder called once; no
  "Event loop is closed"), `test_sweeper_handler_returns_resent_count` (SQLite +
  `InMemoryJobQueue`), `test_migrate_handler_runs_migrations`,
  `test_handlers_load_ssm_when_path_set` (fake loader called once before settings).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5: Commit** `Add Lambda handlers for the worker, sweeper, and migrations`.

### Task 6: Token verification and route permissions

**Files:**
- Create: `apps/api/src/incidentflow/core/auth.py`
- Modify: `core/config.py` (replace `keycloak_issuer_url`/`keycloak_audience` with
  `oidc_issuer_url: str | None = None`, `oidc_client_id: str | None = None`), `api/routes/*.py`,
  `pyproject.toml` (`PyJWT[crypto]`), `.env.example`
- Test: `apps/api/tests/test_auth.py`, route tests

**Interfaces:**
- `@dataclass(frozen=True) class Principal: username: str; groups: frozenset[str]`
- `verify_access_token(token: str, settings: Settings, *, jwks_client: PyJWKClient | None = None)
  -> Principal`: RS256 via JWKS at `{issuer}/.well-known/jwks.json`; checks `iss`, `exp`,
  `token_use == "access"`, `client_id == oidc_client_id`. Raises `AuthenticationError`.
- `get_principal(request) -> Principal` dependency: auth disabled → `Principal("local-operator",
  frozenset({"operator"}))`; missing/invalid bearer → 401 `{"detail": "Authentication required."}`
  with `WWW-Authenticate: Bearer`; JWKS fetch error → 503.
- `require_role(*roles: str)` dependency factory → 403 `{"detail": "Not allowed."}`. `operator`
  implies `viewer`. Reads (`GET` incidents, investigations, trace) need `viewer`; `POST` start,
  resolve, memory-lessons, incident create need `operator`.
- The resolve route replaces `decision.actor` with `principal.username` when auth is enabled.
- With `AUTH_ENABLED=true` and either OIDC setting missing, `create_app()` raises at startup.

- [ ] **Step 1: Failing tests** (RSA key generated in the test, JWKS served by a fake
  `PyJWKClient`): `test_valid_operator_token_starts_investigation`,
  `test_missing_token_returns_401`, `test_expired_token_returns_401`,
  `test_wrong_client_id_returns_401`, `test_id_token_rejected`, `test_viewer_cannot_start_returns_403`,
  `test_user_without_group_gets_403_on_reads`, `test_jwks_unreachable_returns_503`,
  `test_resolve_records_token_username_as_actor`, `test_auth_disabled_keeps_local_behaviour`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5: Commit** `Verify Cognito access tokens and enforce viewer and operator roles`.

### Task 7: MongoDB MCP over stdio

**Files:**
- Modify: `agent/mcp_clients/mongodb.py`, `agent/tools/data_intelligence_tools.py`,
  `core/config.py`, `.env.example`
- Test: `tests/test_mongodb_mcp_client.py`

**Interfaces:**
- Settings: `mongodb_mcp_transport: Literal["http", "stdio"] = "http"`,
  `mongodb_mcp_command: str = "mongodb-mcp-server"`, `mongodb_mcp_command_args: str = "--readOnly"`
  (comma-separated, same parsing as CloudWatch), property `mongodb_mcp_stdio_arguments`.
- `MongoDBMCPClient(server_url: str | None, connection_string: str, *, command: str | None = None,
  command_args: tuple[str, ...] = ())`: stdio when `command` is set, else HTTP; raises
  `ValueError` if neither. Stdio env = current env plus `HOME=/tmp` when `HOME` is unwritable or
  unset, and `MDB_MCP_LOG_PATH=/tmp/mongodb-mcp` (check the pinned server's documented variable
  names when building the image in Task 8). The `connect` tool flow is unchanged.

- [ ] **Step 1: Failing tests**: `test_stdio_transport_when_command_configured`,
  `test_http_transport_by_default`, `test_requires_url_or_command`,
  `test_data_intelligence_tool_passes_stdio_settings`.
- [ ] **Step 2–4:** run → FAIL, implement, `pytest -q` → PASS.
- [ ] **Step 5: Commit** `Run the MongoDB MCP server as a subprocess when configured`.

### Task 8: Lambda-ready image

**Files:**
- Modify: `apps/api/Dockerfile`, `apps/api/pyproject.toml` (`awslambdaric`)
- Modify: `docs/docker-local.md` (one paragraph: same image, Lambda pieces inert locally)

**Interfaces:**
- Image keeps `CMD uvicorn ... --port 8000` (local and api Lambda). Adds:
  `COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter`;
  Node 22 runtime and `mongodb-mcp-server` at a pinned exact version installed globally;
  `awslambdaric` in the app deps. The worker/sweeper/migrate Lambdas override the command with
  `python -m awslambdaric incidentflow.lambda_handlers.<name>` (set in CDK, Task 9).
- Everything the subprocesses write goes to `/tmp` (`HOME`, npm cache, MCP logs).

- [ ] **Step 1:** `docker build -t incidentflow-api:lambda apps/api` succeeds (`--platform linux/amd64`).
- [ ] **Step 2:** With `docker run --rm --read-only --tmpfs /tmp -e HOME=/tmp`:
  `python -c "import incidentflow.lambda_handlers, awslambdaric"` exits 0;
  `mongodb-mcp-server --version` prints the pinned version;
  `/opt/cloudwatch-mcp/bin/awslabs.cloudwatch-mcp-server --help` exits 0.
- [ ] **Step 3:** `docker compose up --build -d` still reaches a COMPLETED investigation (smoke
  start via the dashboard or curl).
- [ ] **Step 4: Commit** `Make the API image runnable as Lambda functions`.

### Task 9: CDK app — backend, auth, frontend, budget

**Files:**
- Create: `infra/cdk/app.py`, `infra/cdk/cdk.json`, `infra/cdk/requirements.txt`
  (`aws-cdk-lib`, `constructs`, `pytest`), `infra/cdk/incidentflow_cdk/stack.py`,
  `infra/cdk/incidentflow_cdk/github_deploy_stack.py`, `infra/cdk/tests/test_stack.py`
- Modify: `.github/workflows/ci.yml` (new `infra` job: `pip install -r requirements.txt`,
  `pytest`; needs Node for the CDK CLI only if `cdk synth` is run — the assertions use
  `Template.from_stack`, so no CLI needed)

**Interfaces:**
- `IncidentFlowStack(scope, id, *, image_tag: str, budget_email: str | None, **kwargs)`.
  `image_tag` from context `imageTag` (default `"latest"` for tests); `budget_email` from context
  `budgetEmail` (budget subscribers omitted when absent).
- Resources: ECR repository `incidentflow-api` (lifecycle: keep 5 images) owned by
  **`GithubDeployStack`** so CI can push before the main stack deploys; DynamoDB table for Jira
  tokens (on-demand, schema matching `DynamoDBStore`'s create-table defaults); SQS queue +
  DLQ; four `DockerImageFunction`s from that repo/tag (x86_64); API Gateway HTTP API with Cognito
  JWT authorizer on `ANY /api/{proxy+}`; Cognito user pool (no self sign-up, TOTP MFA optional →
  `mfa=OPTIONAL` with `otp=True`, groups `viewer` and `operator`), domain prefix
  `incidentflow-<account>`, app client (code + PKCE, no secret, callback/logout =
  `https://<distribution domain>/`); S3 bucket (private, OAC) + CloudFront (`/api/*` →
  API Gateway origin, all methods, no caching, forward `Authorization`); EventBridge rule
  `rate(15 minutes)` → sweeper; Budget; log groups with 14-day retention.
- Worker env: `JOB_TIMEOUT_SECONDS=780`, `JOB_QUEUE_URL`, `MCP_OAUTH_TOKEN_STORE=dynamodb`,
  `MCP_OAUTH_DYNAMODB_TABLE`, `MONGODB_MCP_TRANSPORT=stdio`, `GITHUB_MCP_TRANSPORT=http`,
  `GITHUB_MCP_URL=https://api.githubcopilot.com/mcp/`, `CLOUDWATCH_MCP_COMMAND=/opt/cloudwatch-mcp/bin/awslabs.cloudwatch-mcp-server`,
  `CLOUDWATCH_MCP_COMMAND_ARGS=""`, `DATABASE_NULL_POOL=true`, `INCIDENTFLOW_SSM_PATH=/incidentflow/`,
  `HOME=/tmp`, integration `*_ENABLED=true` flags. Api env: `AUTH_ENABLED=true`,
  `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `AWS_LWA_PORT=8000`, `AWS_LWA_READINESS_CHECK_PATH=/health`.
- IAM: every function reads `ssm:GetParametersByPath`/`GetParameter` on
  `arn:aws:ssm:us-east-1:<acct>:parameter/incidentflow*` (+ `kms:Decrypt` via the AWS-managed
  key); worker gets read-only CloudWatch/Logs actions the three approved MCP tools need, and
  read/write on the token table; api gets `sqs:SendMessage`; sweeper `sqs:SendMessage`.
- Stack outputs: `DistributionDomain`, `DistributionId`, `WebBucket`, `UserPoolId`,
  `UserPoolClientId`, `CognitoDomain`, `MigrateFunctionName`.
- `GithubDeployStack`: GitHub OIDC provider and role `incidentflow-github-deploy` trusting only
  `repo:YanivBohbot/incidentflow:ref:refs/heads/master` (aud `sts.amazonaws.com`), allowed to
  assume the CDK bootstrap roles, push to the ECR repo, invoke the migrate function, sync the web
  bucket, invalidate the distribution. Output `DeployRoleArn`, `RepositoryUri`.

- [ ] **Step 1: Failing assertion tests** (`Template.from_stack`):
  `test_no_vpc_or_nat`, `test_every_log_group_has_14_day_retention`,
  `test_budget_is_10_usd_monthly`, `test_no_lambda_environment_value_looks_secret`
  (no env key containing `KEY`, `SECRET`, `TOKEN`, `PASSWORD` with a non-name value),
  `test_queue_visibility_at_least_worker_timeout`, `test_worker_max_concurrency_2_batch_1`,
  `test_dlq_after_3_receives`, `test_api_routes_use_jwt_authorizer`,
  `test_self_signup_disabled`, `test_sweeper_every_15_minutes`, `test_functions_are_x86_64`,
  `test_deploy_role_trusts_only_master_of_repo`.
- [ ] **Step 2: Run** `cd infra/cdk && pytest` → FAIL. **Step 3: Implement.** **Step 4:** PASS.
- [ ] **Step 5: Commit** `Describe the AWS deployment as a CDK app`.

### Task 10: Dashboard sign-in

**Files:**
- Create: `apps/web/src/auth.ts`, `apps/web/src/auth.test.ts`
- Modify: `apps/web/src/api.ts`, `apps/web/src/main.tsx` (or `App.tsx`), `apps/web/package.json`
  (`oidc-client-ts` exact version), `apps/web/src/vite-env.d.ts`

**Interfaces:**
- Build-time env: `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, `VITE_OIDC_REDIRECT_URI`,
  `VITE_OIDC_LOGOUT_URI`, `VITE_COGNITO_DOMAIN`. All unset → `authEnabled() === false` and the app
  behaves exactly as today.
- `auth.ts`: `authEnabled(): boolean`, `getAccessToken(): Promise<string | null>`,
  `signIn(): Promise<void>`, `completeSignInIfCallback(): Promise<void>` (called before render;
  strips `code`/`state` from the URL), `signOut(): Promise<void>` (Cognito logout URL). Uses
  `UserManager` with `sessionStorage`, scope `openid`, PKCE.
- `api.ts` `request`/`requestOperational`: add `Authorization: Bearer <token>` when enabled; on
  401 call `signIn()` and throw the `ApiError`.
- A small "Sign out" button in the header when enabled.

- [ ] **Step 1: Failing tests**: `adds bearer header when signed in`,
  `redirects to sign-in on 401`, `sends no header when auth is not configured`.
- [ ] **Step 2–4:** `npm test` FAIL → implement → `npm test`, `npm run lint`, `npm run build` PASS.
- [ ] **Step 5: Commit** `Sign in to the dashboard with Cognito when configured`.

### Task 11: Deploy workflow and setup guide

**Files:**
- Create: `.github/workflows/deploy.yml`, `docs/aws-deployment.md`
- Modify: `README.md` (one section linking the guide)

**Interfaces:**
- `deploy.yml`: `on: workflow_run` of "Continuous Integration" completed on `master` with
  `conclusion == success` (plus `workflow_dispatch`); `permissions: id-token: write, contents:
  read`; `concurrency: deploy` (no cancel). Steps: `aws-actions/configure-aws-credentials` with
  `role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}`, region `us-east-1`; ECR login; build and push
  `incidentflow-api:${{ github.sha }}` (linux/amd64); `npx aws-cdk@<pinned> deploy IncidentFlowStack
  --require-approval never -c imageTag=${{ github.sha }} -c budgetEmail=${{ vars.BUDGET_EMAIL }}
  --outputs-file outputs.json`; `aws lambda invoke` the migrate function and fail on
  `FunctionError`; build web with `VITE_OIDC_*` from `outputs.json`; `aws s3 sync dist s3://<bucket>
  --delete`; `aws cloudfront create-invalidation --paths "/*"`. Only repository variables
  (non-secret), no AWS keys.
- `docs/aws-deployment.md` (French, the owner's language): ordered one-time setup — AWS CLI
  profile; `cdk bootstrap aws://<acct>/us-east-1`; deploy `GithubDeployStack` by hand; set the
  GitHub variables; first image push and `IncidentFlowStack` deploy by hand (same commands as the
  workflow) while the branch is unmerged; Neon project (pooled + direct URLs); Atlas M0
  (read-only user, `0.0.0.0/0` with the documented trade-off), load data with
  `scripts/seed_mongodb_scenarios.js` / `seed_demo_scenarios.py`; every SSM parameter by exact
  name (`/incidentflow/OPENAI_API_KEY`, `PINECONE_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`,
  `MONGODB_MCP_CONNECTION_STRING`, `DATABASE_URL`, `LANGGRAPH_CHECKPOINT_DATABASE_URL`,
  `MCP_OAUTH_STORAGE_ENCRYPTION_KEY`, optional `LANGSMITH_API_KEY`) with
  `aws ssm put-parameter --type SecureString` (non-secret values such as the GitHub repository
  allowlist, Pinecone index and CloudWatch log groups are CDK context values passed to the
  Lambda env, set as GitHub variables for the workflow);
  `authorize_jira.py` with `MCP_OAUTH_TOKEN_STORE=dynamodb`; create the Cognito user and add it to
  `operator` (`admin-create-user`, `admin-add-user-to-group`); OpenAI spending limit; the live
  checklist from the spec's Testing section; how to `cdk destroy`.

- [ ] **Step 1:** `actionlint .github/workflows/deploy.yml` (or `npx action-validator`) passes.
- [ ] **Step 2:** Every command in the guide names a real setting, output, or script from Tasks
  1–10 (reviewer checks).
- [ ] **Step 3: Commit** `Deploy from GitHub Actions and document the one-time AWS setup`.

### Task 12: First deployment and live check (with the owner)

Not dispatched to a subagent; done after the final branch review, with the owner at the keyboard
for every step that touches their AWS, Neon, Atlas, Atlassian, or GitHub accounts.

- [ ] Follow `docs/aws-deployment.md` to the first deploy.
- [ ] Live checklist: `curl https://<domain>/api/incidents` → 401; sign in; start an
  investigation → COMPLETED with findings from all five integrations; approve one Jira write
  (ticket created) and reject another; trace readable; the budget exists.

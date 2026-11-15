# Serverless AWS deployment with Cognito sign-in

## Intent

IncidentFlow runs only on the owner's PC (docker compose, plus a host-run MongoDB MCP server). The
previous step (`docs/superpowers/specs/2026-11-15-investigation-job-queue-design.md`) decoupled
accepting an investigation from executing it, so that the same job code could run in a Lambda.
This step puts the whole product online on the owner's AWS account, so the owner can open a URL,
sign in, and run a real investigation over all five integrations, exactly as it works locally.

It is a **demo for the owner alone, for now**. It is also the first piece of the enterprise
roadmap that is deployed: infrastructure as code, automatic deployment, real sign-in, no secrets
on disk. Event ingestion (CloudWatch alarm → EventBridge → SQS) is the next step and will plug into
the queue created here.

## Decisions made by the owner

- Deploy **serverless** on the owner's AWS account, budget about **$10/month**.
- Audience: **the owner only**, for a demo.
- **All five integrations work in the cloud, as locally**: Jira (including approved writes; local
  `.env` has `JIRA_MCP_WRITE_ENABLED=true`), MongoDB, Pinecone, GitHub, CloudWatch.
- Sign-in with **AWS Cognito**, now (it was parked; it is pulled into this step).
- **No separation of duties**: the owner may approve their own Jira writes. Do not build that rule.
- Deployment runs **automatically from GitHub Actions** on merge to `master`.

## Goals

- `cdk deploy` (from CI) creates or updates everything; `cdk destroy` removes it. Nothing is
  created by hand in the console except the one-time setup listed below.
- The owner opens the CloudFront URL, signs in through Cognito, and uses the dashboard as locally:
  start an investigation, watch it run, approve or reject a Jira write, read the trace.
- Every `/api/*` call without a valid Cognito token is rejected before any Lambda code runs.
- The approving `actor` recorded on a human review comes from the verified token, not from the
  request body.
- A merge to `master` with green CI deploys the new version with no manual step.
- Jira works non-interactively in Lambda: tokens are stored durably and encrypted on AWS, refreshed
  by the worker, and a missing/expired authorization fails the Jira step immediately with a clear
  message instead of waiting for a browser callback.
- The local docker compose stack keeps working unchanged (auth off locally unless configured).

## Non-goals

- Event ingestion, alert deduplication, trigger rules (next step).
- Custom domain name, staging environment, multi-region, multi-tenant.
- Observability beyond Lambda's default CloudWatch Logs (roadmap item 3).
- Fine-grained RBAC and separation of duties.
- Changing agents, prompts, guardrails, or the supervisor's behaviour (e.g. it re-proposing a Jira
  write after a rejection stays as is).
- Self sign-up, password-reset UX beyond what Cognito's managed login provides.

## Anti-goals (proposed by me, owner did not have specific ones)

- **A surprise bill.** Nothing with a fixed monthly cost: no NAT gateway, no VPC for the Lambdas,
  no RDS, no Secrets Manager secrets ($0.40 each), no provisioned concurrency, no always-on
  containers. Log groups have a retention period. An AWS Budget alarm at $10 exists.
- **A leaked secret.** No secret in the repo, the image, GitHub, Lambda environment variables in
  plain text, or logs. GitHub Actions holds no AWS keys.
- **Breaking local development or the test suite.** Tests still need no AWS, no internet.
- **An unauthenticated way to spend OpenAI credits or write to Jira.**

## Architecture

```
Browser ──▶ CloudFront ──┬─ /*      ──▶ S3 (built React dashboard, private, OAC)
                         └─ /api/*  ──▶ API Gateway HTTP API (Cognito JWT authorizer)
                                              │
                                              ▼
                                        Lambda "api" (FastAPI)  ──▶ Neon Postgres
                                              │ send {"investigation_id"}
                                              ▼
                                        SQS jobs queue ── DLQ after 3 receives
                                              │ event source mapping, batch size 1
                                              ▼
                                        Lambda "worker" ──▶ OpenAI, Jira (HTTP), GitHub (HTTP),
                                                            Pinecone; subprocesses: CloudWatch MCP,
                                                            MongoDB MCP ──▶ MongoDB Atlas M0
EventBridge schedule ──▶ Lambda "sweeper"
CI ──▶ Lambda "migrate" (alembic upgrade head + checkpointer setup)
```

Region: **us-east-1** (where the owner's CloudWatch alarms are). Lambdas are **not in a VPC**.
Serving the API under the same CloudFront distribution as the dashboard means one origin, so no
CORS configuration.

### One image, four Lambdas

All four Lambdas use **one container image** built from `apps/api` and pushed to ECR (a zip cannot
hold the CloudWatch MCP virtualenv and the MongoDB MCP server). They differ by entry point:

- **api**: runs the existing FastAPI app unchanged (my call: AWS Lambda Web Adapter in front of
  uvicorn, so `main.create_app()` and its lifespan run as today; an ASGI adapter such as Mangum is
  acceptable if the builder prefers, as long as the lifespan still runs).
- **worker**: an SQS handler that, for each record, calls the existing
  `InvestigationJobProcessor.process(id, keep_alive=...)`. `keep_alive` extends the DB lease and
  the message visibility as the local worker does. The workflow and checkpointer are built once per
  Lambda execution environment (cold start) and reused across invocations.
  - Batch size 1, event-source **maximum concurrency 2** (the smallest allowed; matches today's
    `WORKER_CONCURRENCY=2` and caps OpenAI spend).
  - Function timeout **900 s** (Lambda maximum); `JOB_TIMEOUT_SECONDS` lowered to about **780 s**
    so a run that hits the deadline is persisted as `FAILED` before Lambda kills the process.
  - Queue visibility timeout ≥ function timeout, as Lambda requires for SQS sources.
  - The outcome of `process()` decides the record's fate: persisted results and dropped duplicates
    are acknowledged (successful batch item); an unexpected crash lets SQS redeliver, and the
    existing lease/attempt rules handle the retry (`ReportBatchItemFailures`).
- **sweeper**: calls the existing `sweep_stale_investigations`. Neon's free plan suspends compute
  after 5 minutes idle and has a monthly compute-hour quota, so a once-a-minute sweeper would keep
  the database awake around the clock and exhaust it. Run it **every 15 minutes or less often**;
  with SQS redelivering crashed jobs by itself, the sweeper only covers the rare "committed but
  never sent" case.
- **migrate**: runs `alembic upgrade head` and the LangGraph `checkpointer.setup()` (follow-up from
  the job-queue step), invoked by the deploy workflow after `cdk deploy`.

The image keeps the CloudWatch MCP virtualenv it has today, adds the **MongoDB MCP server**
(Node runtime + a pinned `mongodb-mcp-server` version, installed at build time), and runs as a
non-root user. Lambda's filesystem is read-only except `/tmp`; anything that writes (uv/npm
caches, MCP subprocess state) must point at `/tmp`. An ECR lifecycle rule keeps only the last few
images.

### Integrations in the cloud

| Integration | Local today | On AWS |
|---|---|---|
| CloudWatch | `uv`/venv stdio subprocess with the `incidentflow` AWS profile | same subprocess; credentials from the worker's **IAM role** (read-only CloudWatch + Logs), no profile, no keys |
| GitHub | Docker stdio | GitHub's hosted MCP over HTTP (`GITHUB_MCP_TRANSPORT=http`), PAT from SSM; the client already sends `X-MCP-Readonly: true` |
| Pinecone | direct SDK | unchanged, API key from SSM |
| Jira | Atlassian MCP over HTTP, OAuth tokens in a local encrypted DiskStore | same server; tokens in an AWS-backed store (below) |
| MongoDB | MCP server over HTTP on the host, local MongoDB | **MongoDB Atlas M0** (free) loaded with the same demo data; MCP server as a **stdio subprocess** of the worker; the `MongoDBMCPClient` gains a stdio transport next to HTTP (HTTP stays the local default) |

The Atlas cluster's network access list must allow Lambda's egress. Lambda without a VPC has no
fixed IP, so the demo uses `0.0.0.0/0` protected by the database user's strong password and a
read-only database role. This is a known demo trade-off, recorded here.

### Jira tokens without a browser

Today `JiraMCPClient._oauth_auth` wraps a `DiskStore` in `FernetEncryptionWrapper`. On AWS:

- The token store is a durable AWS key-value store behind the same `FernetEncryptionWrapper`
  (my call: a DynamoDB on-demand table, always-free at this size, via a `py-key-value` store or a
  small custom store; an SSM-backed store is acceptable). The store choice is a setting; local
  keeps `DiskStore`.
- The Fernet key lives in SSM (SecureString).
- **First authorization** happens once on the owner's PC: a script (extending
  `scripts/verify_jira_read_access.py`) runs the browser OAuth flow and writes the resulting
  tokens into the AWS store.
- The worker refreshes tokens with the refresh token and writes rotated tokens back to the store.
- When no usable token exists and a refresh is impossible, the Jira client **fails immediately**
  with an error such as "Jira authorization expired; run the Jira authorization script", which the
  existing graceful-degradation path turns into a zero-confidence Jira finding. It must never start
  the local callback server or wait for a browser in Lambda.
- The same fail-fast behaviour fixes the 300-second hang seen in containers during the job-queue
  live test.

### Sign-in and authorization

- CDK creates a **Cognito User Pool**: self sign-up disabled, accounts created by an admin, TOTP
  MFA (no SMS cost), managed login pages, an app client using authorization code + PKCE with the
  CloudFront URL as callback and logout URL.
- **API Gateway** has a JWT authorizer on `/api/*` for this pool and client. `/health*` and
  `/operations/*` are either behind the same authorizer or not routed publicly (builder's choice;
  nothing unauthenticated may start work or read investigation data).
- **The API also verifies the token itself** (issuer, audience/client id, signature via JWKS,
  expiry) when `AUTH_ENABLED=true`, so the app is not secure only because of its gateway. Settings
  are generic OIDC (issuer URL, audience); the existing `keycloak_*` settings are renamed or
  replaced. With `AUTH_ENABLED=false` (local default) behaviour stays as today.
- Roles (my call, minimal): Cognito groups `viewer` (read) and `operator` (start investigations,
  resolve reviews, record memory lessons); a signed-in user in neither group gets 403. The owner's
  account is in `operator`. A small `require_permission` dependency on the routes; no
  separation-of-duties check.
- The resolve endpoint and memory-lesson endpoint record the token's user (e.g. `email` or
  `cognito:username`) as the actor; a body-supplied `actor` is ignored when auth is on.
- The dashboard signs in with a small OIDC library (my call: `oidc-client-ts`), keeps tokens in
  memory/session storage, sends `Authorization: Bearer`, and redirects to sign-in on 401. With no
  OIDC configuration (local), it behaves as today.

### Configuration and secrets

- Secrets in **SSM Parameter Store SecureString** (standard tier, free; AWS-managed KMS key):
  OpenAI API key, Pinecone API key, GitHub PAT, Atlas connection string, Neon database URL(s),
  Jira Fernet key, LangSmith key if tracing is kept on.
- Lambdas read secrets at cold start from SSM (by parameter name passed in a plain environment
  variable), not as plaintext environment values. Their IAM role can read only
  `/incidentflow/*` parameters.
- Non-secret settings (`*_ENABLED` flags, repository allowlist, index names, queue URL, region)
  are plain Lambda environment variables set by CDK.
- `JOB_QUEUE_REGION` falls back to `AWS_REGION` (follow-up from the job-queue step).

### Deployment

- New directory `infra/cdk/` (Python CDK app) with the stacks above.
- The existing `ci.yml` is unchanged in what it checks.
- New `deploy.yml`: runs on push to `master` after CI passes. Steps: assume the deploy role via
  **GitHub OIDC**, build and push the image to ECR, `cdk deploy`, invoke the migrate Lambda, build
  the web app with the deployed Cognito/API settings, sync to S3, invalidate CloudFront.
- The deploy IAM role trusts only `repo:YanivBohbot/incidentflow:ref:refs/heads/master` and is
  scoped to what CDK deploys need (the CDK bootstrap roles).
- **One-time setup, documented step by step** in `docs/aws-deployment.md` (French or English,
  builder's choice; the owner reads French): `cdk bootstrap`, the GitHub OIDC provider and deploy
  role, creating the Neon project and Atlas M0 cluster, loading the Mongo demo data, putting each
  secret in SSM, running the Jira authorization script, creating the owner's Cognito user and
  adding it to `operator`, setting an OpenAI spending limit. Personal data (the owner's email) is
  entered at setup time, never committed.

### Cost guardrails

- AWS Budget at **$10/month** with email alerts at 50 %, 80 %, 100 % (email supplied at setup,
  not committed).
- Log retention 14 days on every log group.
- Expected AWS cost for demo use is near zero (Lambda, SQS, API Gateway, CloudFront, DynamoDB,
  EventBridge within free tiers; ECR storage of a few hundred MB is cents). Neon and Atlas are on
  free plans. OpenAI usage is the real cost and is outside AWS budgets.

### Follow-ups from the job-queue step included here

Several API Lambda instances can now run at once, so:

- a **partial unique index** on active (`PENDING`/`RUNNING`) investigations per incident backs the
  409 check against races;
- call `keep_alive` right after the claim;
- use database time for leases and `updated_at` (Lambda clocks are fine, but the rule removes the
  question);
- `checkpointer.setup()` runs in migrate, not at every cold start.

## Testing

- Unit tests stay offline: the SQS Lambda handler is tested with a fake event and the
  `InMemoryJobQueue`/fake processor (acknowledge vs. batch item failure); the sweeper handler with
  SQLite; the JWT verification with a locally generated key and JWKS; route permission tests via
  dependency overrides; the Jira store with an in-memory key-value store and a fake OAuth that
  must fail fast instead of opening a callback server; the MongoDB stdio transport selection.
- `cdk synth` runs in CI with assertions on the things that cost money or leak: no VPC/NAT, log
  retention set, budget present, Lambda env has no secret values, queue visibility ≥ worker
  timeout, worker max concurrency 2.
- Live verification after the first deploy (manual, listed in the setup doc): sign in, start an
  investigation, see it complete with findings from all five integrations, approve and reject a
  Jira write, check that an unauthenticated `curl /api/incidents` returns 401.

## Answers to the builder check

- **Base branch.** The job-queue work is still on `feature/investigation-job-queue` (owner chose
  not to merge it yet). This work goes on a new branch stacked on it; both reach `master` together
  when the owner merges, and only then does `deploy.yml` fire. Until then the first deploy can be
  run by hand with the same commands the workflow uses.
- **Jira OAuth state.** The AWS store holds **everything fastmcp's `OAuth` keeps in its
  `token_storage`** (tokens and the dynamically registered client information), not only the
  access/refresh tokens. The authorization script writes all of it. A missing client registration
  is treated like a missing token: fail fast, "re-authorize". **First plan task is a spike**: from
  a process other than the one that authorized (a fresh container), load the stored state and
  refresh the token against Atlassian. If refresh is bound to the original host or redirect, stop
  and bring the Jira design back to the owner.
- **Neon connections.** API and worker SQLAlchemy use Neon's **pooled** URL with `NullPool` (or a
  pool of 1) and no server-side prepared statements; the LangGraph `AsyncPostgresSaver` and the
  migrate Lambda use the **direct** URL (`LANGGRAPH_CHECKPOINT_DATABASE_URL` is set). A few
  seconds of delay when Neon wakes from suspend is acceptable for a demo; connections use a
  connect timeout long enough to cover it (no extra retry layer).
- **Which token.** The dashboard sends the Cognito **access token**. API Gateway and the API check
  issuer, `client_id`, `token_use=access`, signature and expiry; groups come from
  `cognito:groups`. The recorded actor is `cognito:username` (no email is stored or logged).
- **Data.** Atlas is loaded with the existing seed scripts (`scripts/seed_mongodb_scenarios.js`,
  `seed_demo_scenarios.py` as applicable), run by hand during setup. Pinecone keeps the owner's
  existing cloud indexes; no ingestion in CI or CDK. Neither CI nor CDK touches data.
- **Architecture.** Images and Lambdas are **x86_64** (no QEMU build on GitHub's runners, no risk
  of an arm-only gap in the MCP servers; the cost difference is negligible at demo volume).
- **Deploy during a run.** Acceptable for a single-user demo that an in-flight run fails or is
  retried through the existing lease/attempt rules. Migrations must stay backward-compatible with
  the previous image (additive first, removals later).

## Left to the builder

- Stack split inside the CDK app, construct names, file layout under `infra/cdk/`.
- Lambda memory sizes (worker likely 2–3 GB because of the MCP subprocesses), exact sweeper
  interval (≥ 15 min).
- Lambda Web Adapter vs. an ASGI adapter for the api Lambda.
- DynamoDB vs. SSM for the Jira token store.
- How the dashboard reads its deployed config (build-time Vite env vars or a `config.json`
  uploaded with the build).
- Whether to put `/health` behind the authorizer.

## Calls I made (owner can override)

- AWS CDK in Python (same language as the API) rather than SAM or Terraform.
- One container image for every Lambda; MongoDB MCP and CloudWatch MCP as worker subprocesses.
- API and dashboard behind one CloudFront distribution (no CORS).
- API verifies tokens itself in addition to API Gateway.
- Two roles only (`viewer`, `operator`).
- DynamoDB for Jira tokens; SSM SecureString for every other secret.
- Atlas open to `0.0.0.0/0` for the demo (Lambda has no fixed IP without a paid NAT).
- Budget alarm at $10, log retention 14 days, sweeper every 15 minutes.
- Run deadline lowered to ~780 s to fit Lambda's 15-minute cap.

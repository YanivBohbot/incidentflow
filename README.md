# IncidentFlow

**AI-powered incident investigation with a durable, human-supervised multi-agent workflow.**

IncidentFlow helps on-call engineers investigate production incidents. An operator declares an
incident ("Payment API has returned HTTP 500 errors since this morning"), and a supervisor agent
delegates the investigation to specialist sub-agents that gather evidence from Jira, MongoDB
operational events, a Pinecone knowledge base, and GitHub. The result is a structured
investigation report with evidence, hypotheses, and a confidence score.

Every sensitive step stays under human control. Jira writes and report-level reviews pause the
workflow until an operator approves or rejects them. Lessons learned are added to the incident
memory only after an operator confirms them.

---

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Repository structure](#repository-structure)
- [Getting started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Option A: run everything with Docker Compose](#option-a-run-everything-with-docker-compose)
  - [Option B: run the API and web app locally](#option-b-run-the-api-and-web-app-locally)
  - [Enabling external integrations](#enabling-external-integrations)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Testing and quality](#testing-and-quality)
- [Security design](#security-design)

---

## Features

- **Incident management:** create, list, update, and delete incidents with a priority and status.
- **Multi-agent investigations:** a supervisor agent selects and delegates to five specialists:

  | Specialist        | Tool                    | Evidence source                                        |
  | ----------------- | ----------------------- | ------------------------------------------------------ |
  | IT Operations     | `ask_it_operations`     | Jira Cloud (official Atlassian MCP server, OAuth)      |
  | Data Intelligence | `ask_data_intelligence` | MongoDB operational events (MongoDB MCP server)        |
  | Knowledge         | `ask_knowledge`         | Pinecone: NIST incident-response guides, runbooks, resolved incidents |
  | GitHub            | `ask_github`            | Recent code changes (GitHub MCP server, read-only)     |
  | CloudWatch Observability | `ask_cloudwatch` | AWS CloudWatch alarms, metrics, and Logs Insights (AWS Labs CloudWatch MCP server, read-only) |

- **Structured reports:** the supervisor returns a schema-validated `InvestigationReport`.
- **Durable, resumable workflows:** LangGraph state is checkpointed in PostgreSQL, so a paused
  investigation survives an API restart.
- **Human-in-the-loop at two levels:** report reviews and approval-gated Jira writes
  (create issue / add comment).
- **Curated incident memory:** operators confirm lessons from completed investigations, which are
  then indexed in Pinecone and retrieved by later investigations.
- **Graceful degradation:** a disabled or unavailable integration returns a zero-confidence finding
  instead of failing the whole investigation.
- **Observability:** LangSmith tracing, request correlation IDs, response-time headers, aggregated
  operational metrics, and health/readiness probes.
- **Web dashboard:** overview, incidents, investigations, and approvals pages.

## How it works

```mermaid
flowchart LR
    UI[React dashboard] -->|/api| API[FastAPI]
    API --> SVC[InvestigationService]
    SVC -->|persist lifecycle| PG[(PostgreSQL)]
    SVC -->|ainvoke / resume| WF

    subgraph WF[LangGraph investigation workflow]
        direction LR
        V[validate] --> P[prepare] --> I[investigate] --> C[capture_report]
        C -->|review required| R[review<br/>interrupt]
        C --> F[finalize]
        R --> F
        V -->|invalid| X[fail]
    end

    WF -.checkpoints.-> PG
    I --> SUP[Supervisor agent]
    SUP --> J[IT Operations<br/>Jira MCP]
    SUP --> D[Data Intelligence<br/>MongoDB MCP]
    SUP --> K[Knowledge<br/>Pinecone]
    SUP --> G[GitHub<br/>GitHub MCP]
    SUP --> C[CloudWatch Observability<br/>CloudWatch MCP]
```

1. **Start.** `POST /api/investigations` creates an investigation row (`PENDING` → `RUNNING`) and
   invokes the workflow on a thread dedicated to that investigation.
2. **Validate.** Empty or oversized requests (over 5,000 characters) are rejected before any
   model or external call.
3. **Investigate.** The `investigate` node calls the supervisor (a LangChain `create_agent`). A
   middleware chain bounds its behavior:
   - `LLMToolSelectorMiddleware` pre-selects at most five relevant specialists;
   - `ToolRetryMiddleware` retries read-only delegations once on network errors;
   - `ToolCallLimitMiddleware` caps each specialist at two calls per run;
   - the node itself has a LangGraph retry policy and a failure handler.
4. **Delegate.** Each specialist tool opens its MCP client, builds a specialist agent with its own
   prompt, allowlisted tools, and typed finding contract, and returns the finding as JSON.
5. **Report.** The supervisor's output is validated as an `InvestigationReport` using
   `ToolStrategy`. Schema errors are sent back to the model so it can correct the report instead of
   failing the run.
6. **Review.** The workflow pauses (`AWAITING_HUMAN_REVIEW`) in either of two cases:
   - a review policy requires a report-level review (`interrupt()` in the `review` node);
   - the Jira specialist wants to write, and `HumanInTheLoopMiddleware` interrupts inside the
     nested agent.

   `POST /api/investigations/{id}/human-review/resolve` resumes the same thread with
   `Command(resume=...)`.
7. **Finish.** The final state is saved as `COMPLETED` or `FAILED`.

## Tech stack

| Layer          | Technologies                                                              |
| -------------- | ------------------------------------------------------------------------- |
| API            | Python 3.12/3.13, FastAPI, Pydantic v2, pydantic-settings                  |
| Agents         | LangChain v1 (`create_agent`, middleware), LangGraph v1, OpenAI models     |
| Tool access    | Model Context Protocol (MCP): Jira Cloud, MongoDB, GitHub                 |
| Retrieval      | Pinecone, OpenAI embeddings, LangChain loaders and text splitters         |
| Persistence    | PostgreSQL 16, SQLAlchemy 2, Alembic, LangGraph `AsyncPostgresSaver`      |
| Observability  | LangSmith                                                                 |
| Web            | React 19, TypeScript, Vite, oxlint, nginx                                 |
| Infrastructure | Docker Compose, Keycloak (identity provider, prepared for auth)           |
| CI             | GitHub Actions: Ruff, pytest, oxlint, production web build                |

## Repository structure

```text
incidentflow/
├── apps/
│   ├── api/                         # FastAPI service
│   │   ├── alembic/versions/        # Database migrations
│   │   ├── scripts/                 # Ingestion, evaluation, and live-integration scripts
│   │   ├── src/incidentflow/
│   │   │   ├── api/routes/          # HTTP routers and dependencies
│   │   │   ├── application/services/# Use-case coordination
│   │   │   ├── domain/              # Pydantic contracts (incidents, investigations, reviews, memory)
│   │   │   ├── infrastructure/database/  # SQLAlchemy models and repositories
│   │   │   ├── agent/
│   │   │   │   ├── orchestration/   # Workflow graph, supervisor, checkpoints, policies, fault tolerance
│   │   │   │   ├── agents_specialist/   # Specialist agents and finding contracts
│   │   │   │   ├── tools/           # Supervisor delegation tools
│   │   │   │   ├── mcp_clients/     # Least-privilege Jira, MongoDB, GitHub MCP clients
│   │   │   │   ├── guardrails/      # External-evidence boundary
│   │   │   │   └── prompts/         # System prompts
│   │   │   ├── knowledge/           # Pinecone stores, source loaders, retrieval evaluation
│   │   │   ├── core/                # Settings and operational metrics
│   │   │   └── main.py              # App factory and lifespan
│   │   └── tests/
│   └── web/                         # React + Vite dashboard
├── docs/                            # Local Docker guide, design specs, and plans
├── infra/keycloak/                  # Keycloak realm import
└── docker-compose.yml
```

## Getting started

### Prerequisites

- **Docker** and Docker Compose (for PostgreSQL, or for the full stack)
- **Python 3.12 or 3.13** and **Node.js 22** (for local development)
- An **OpenAI API key**. This is the only external credential required. All other integrations
  are optional.

```bash
git clone https://github.com/YanivBohbot/incidentflow.git
cd incidentflow
```

### Option A: run everything with Docker Compose

1. Create the two environment files from the templates:

   ```bash
   cp .env.example .env                    # Compose: Postgres, Keycloak, web port
   cp apps/api/.env.example apps/api/.env  # API settings
   ```

   On Windows PowerShell, use `Copy-Item` instead of `cp`.

2. Edit them:
   - in `apps/api/.env`, set `OPENAI_API_KEY`;
   - in `.env`, set the Keycloak admin credentials;
   - use the same PostgreSQL password in both files.

   To start without any external integration, set every `*_ENABLED` flag in `apps/api/.env` to
   `false` (see [Configuration](#configuration)).

3. Build and start the stack:

   ```bash
   docker compose up --build -d
   docker compose ps
   ```

   Compose starts PostgreSQL, runs `alembic upgrade head` once, then starts the API, the web app,
   and Keycloak.

| Service         | URL                                  |
| --------------- | ------------------------------------ |
| Web dashboard   | http://127.0.0.1:5173 (or `WEB_PORT`) |
| API docs        | http://127.0.0.1:8000/docs           |
| API readiness   | http://127.0.0.1:8000/health/ready   |
| Keycloak        | http://127.0.0.1:8080                |

Stop the stack with `docker compose down`. Add `--volumes` only if you want to delete the database
and the saved workflow checkpoints. See [`docs/docker-local.md`](docs/docker-local.md) for more
details.

### Option B: run the API and web app locally

1. **Start PostgreSQL only:**

   ```bash
   cp .env.example .env
   docker compose up -d postgres
   ```

2. **Install and run the API** (from `apps/api`):

   ```bash
   cd apps/api
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   cp .env.example .env               # then set OPENAI_API_KEY and DATABASE_URL
   alembic upgrade head
   uvicorn incidentflow.main:app --reload
   ```

   On startup, the API opens the LangGraph PostgreSQL checkpointer and creates its tables.

3. **Run the web app** (from `apps/web`, in another terminal):

   ```bash
   cd apps/web
   npm ci
   npm run dev
   ```

   The Vite dev server (http://localhost:5173) proxies `/api`, `/health`, and `/operations` to the
   API on port 8000.

### Enabling external integrations

Each integration is enabled by its own flag and can be turned on independently.

- **Jira** (`JIRA_MCP_ENABLED=true`): uses the official Atlassian remote MCP server with OAuth.
  The first run opens a browser authorization flow. To keep tokens encrypted on disk, set
  `MCP_OAUTH_TOKEN_STORE_DIR` and `MCP_OAUTH_STORAGE_ENCRYPTION_KEY`. You can generate a key with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
  Keep `JIRA_MCP_WRITE_ENABLED=false` until write access has been reviewed.
- **MongoDB** (`MONGODB_MCP_ENABLED=true`): point `MONGODB_MCP_URL` at a running MongoDB MCP
  server. To load synthetic test events, run
  `mongosh apps/api/scripts/seed_mongodb_test_events.js`.
- **GitHub** (`GITHUB_MCP_ENABLED=true`): by default, the read-only GitHub MCP server runs in
  Docker over stdio. Set `GITHUB_PERSONAL_ACCESS_TOKEN` and list the allowed repositories in
  `GITHUB_MCP_REPOSITORIES` (`owner/repo`, comma-separated).
- **AWS CloudWatch** (`CLOUDWATCH_MCP_ENABLED=true`): the AWS Labs CloudWatch MCP server runs
  over stdio through `uv`. Set `CLOUDWATCH_MCP_AWS_PROFILE` to a read-only profile (leave it empty
  on AWS to use the attached IAM role), `CLOUDWATCH_MCP_AWS_REGION`, and the allowed log groups in
  `CLOUDWATCH_MCP_LOG_GROUPS`. `python scripts/seed_cloudwatch_demo.py` creates a synthetic
  incident and a read-only role for local testing. See
  [docs/cloudwatch-agent.md](docs/cloudwatch-agent.md) for IAM permissions, the full
  read plan, and known limitations.
- **Pinecone** (`PINECONE_ENABLED=true`): create the index manually, then ingest the knowledge
  sources. Both scripts only preview the documents unless you pass `--commit`.

  ```bash
  python scripts/ingest_public_knowledge.py --commit   # official public documentation
  python scripts/ingest_local_knowledge.py --commit    # files placed in apps/api/knowledge_sources/
  ```

  `knowledge_sources/` is git-ignored. Supply your own runbooks, or PDFs such as NIST SP 800-61r3,
  locally. Set `PINECONE_RESOLVED_INCIDENTS_ENABLED=true` to enable the curated incident memory.
- **LangSmith** (`LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`): enables agent tracing.

## Configuration

The API reads its settings from `apps/api/.env`. The main variables are:

| Variable                               | Required | Description                                               |
| -------------------------------------- | -------- | --------------------------------------------------------- |
| `OPENAI_API_KEY`                       | yes      | OpenAI key used by every agent                            |
| `OPENAI_MODEL`                         | no       | Chat model (default `gpt-4.1-mini`)                       |
| `DATABASE_URL`                         | yes      | `postgresql+psycopg://user:password@host:5432/db`         |
| `LANGGRAPH_CHECKPOINT_DATABASE_URL`    | no       | Separate checkpoint database (defaults to `DATABASE_URL`) |
| `API_PREFIX`                           | no       | Route prefix (default `/api`)                             |
| `JIRA_MCP_ENABLED` / `JIRA_MCP_WRITE_ENABLED` | no | Enable Jira reads / approval-gated writes             |
| `MONGODB_MCP_ENABLED`, `MONGODB_MCP_URL` | no     | MongoDB MCP server                                        |
| `GITHUB_MCP_ENABLED`, `GITHUB_MCP_REPOSITORIES`, `GITHUB_PERSONAL_ACCESS_TOKEN` | no | GitHub MCP server and repository allowlist |
| `CLOUDWATCH_MCP_ENABLED`, `CLOUDWATCH_MCP_AWS_PROFILE`, `CLOUDWATCH_MCP_AWS_REGION`, `CLOUDWATCH_MCP_LOG_GROUPS` | no | CloudWatch MCP server, AWS identity, and log group allowlist |
| `PINECONE_ENABLED`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` | no | Knowledge retrieval                          |
| `PINECONE_RESOLVED_INCIDENTS_ENABLED`  | no       | Curated resolved-incident memory                          |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | no     | LangSmith tracing                                         |

The root `.env` is used only by Docker Compose (`POSTGRES_PASSWORD`, Keycloak admin credentials,
`WEB_PORT`).

## API overview

Interactive OpenAPI documentation is available at `/docs` once the API is running.

| Method   | Path                                               | Description                                  |
| -------- | -------------------------------------------------- | -------------------------------------------- |
| `POST`   | `/api/incidents`                                   | Create an incident                           |
| `GET`    | `/api/incidents` · `/api/incidents/{id}`           | List or read incidents                       |
| `PATCH`  | `/api/incidents/{id}`                              | Update an incident                           |
| `DELETE` | `/api/incidents/{id}`                              | Delete an incident                           |
| `POST`   | `/api/investigations`                              | Start an investigation for an incident       |
| `GET`    | `/api/investigations` · `/api/investigations/{id}` | List or read investigations                  |
| `POST`   | `/api/investigations/{id}/human-review/resolve`    | Approve, reject, or request more information |
| `POST`   | `/api/investigations/{id}/memory-lessons`          | Confirm and index a lesson learned           |
| `GET`    | `/health` · `/health/ready`                        | Liveness and readiness                       |
| `GET`    | `/operations/metrics`                              | Aggregated request and lifecycle counters    |

Example:

```bash
# 1. Create an incident
curl -X POST http://127.0.0.1:8000/api/incidents \
  -H "Content-Type: application/json" \
  -d '{"title": "Payment API failures", "description": "Payment API has returned HTTP 500 errors since this morning.", "priority": "HIGH"}'

# 2. Start an investigation (use the returned incident id)
curl -X POST http://127.0.0.1:8000/api/investigations \
  -H "Content-Type: application/json" \
  -d '{"incident_id": "<incident-id>", "incident_request": "Investigate Payment API HTTP 500 errors."}'

# 3. If the investigation is AWAITING_HUMAN_REVIEW, resolve it
curl -X POST http://127.0.0.1:8000/api/investigations/<investigation-id>/human-review/resolve \
  -H "Content-Type: application/json" \
  -d '{"decision": "APPROVE", "actor": "on-call-engineer", "reason": "Evidence confirmed."}'
```

## Testing and quality

The test suite runs without any external service. It uses in-memory SQLite, LangGraph's
`InMemorySaver`, and fake workflows.

```bash
cd apps/api
pytest -q                                        # full suite
pytest tests/test_investigation_workflow.py      # a single file
ruff check src tests scripts                     # lint
ruff format --check src tests                    # formatting

cd ../web
npm run lint
npm run build
```

`apps/api/scripts/` also contains evaluation scripts that run against real services
(`evaluate_supervisor_routing.py`, `evaluate_knowledge_retrieval.py`), plus run and verify scripts
for each live integration.

### LangSmith evaluation

`scripts/evaluate_investigation_reports.py` runs the real investigation workflow on a LangSmith
dataset of incidents with known root causes, and scores every report as a LangSmith experiment:

| Evaluator                     | Type         | Checks                                                     |
| ----------------------------- | ------------ | ---------------------------------------------------------- |
| `required_specialists`        | code         | The specialists the incident depends on were consulted     |
| `evidence_attributed`         | code         | The report has evidence and every item names its source    |
| `no_fabricated_live_evidence` | code         | Disabled integrations are never reported as live evidence  |
| `root_cause_identified`       | LLM-as-judge | The report identifies the expected root cause              |
| `safe_proposed_actions`       | LLM-as-judge | Proposed actions are relevant and avoid known unsafe steps |

```bash
cd apps/api
python scripts/evaluate_investigation_reports.py                       # creates the dataset if missing
python scripts/evaluate_investigation_reports.py --experiment-prefix v2  # compare in LangSmith
```

Jira, MongoDB, and GitHub are disabled by default, so the experiment needs only OpenAI, Pinecone
(with the synthetic playbooks ingested), and `LANGSMITH_API_KEY`. Pass `--live-integrations` to
keep them as configured in `.env`.

GitHub Actions runs Ruff and pytest for the API, and lint and a production build for the web app,
on every push and pull request.

## Security design

- **Least-privilege MCP access:** only explicitly approved tools are exposed to the agents, even
  when the MCP server offers more.
- **Repository allowlist:** a GitHub middleware rejects any call, including `search_code` queries,
  that targets a repository outside `GITHUB_MCP_REPOSITORIES`.
- **Read-only AWS access:** the CloudWatch agent exposes four read tools, rejects per-call AWS
  profile or region overrides and log groups outside `CLOUDWATCH_MCP_LOG_GROUPS`, and passes no
  application secrets to the MCP subprocess. The recommended IAM policy contains only read
  permissions.
- **Untrusted external evidence:** every tool output is wrapped as external evidence before the
  model reads it. This limits prompt injection from tickets, events, or documents.
- **Approval-gated writes:** Jira issue creation and comments always pause for an operator decision.
- **Read-only retrieval:** Pinecone is read-only at runtime. Indexing happens only through explicit
  ingestion scripts or operator-confirmed lessons.
- **Encrypted token cache:** Jira OAuth tokens can be stored encrypted at rest with Fernet.
- **Privacy-aware metrics:** operational metrics aggregate status codes and lifecycle states only,
  never incident content.

# Local Docker environment

This Compose environment runs PostgreSQL, the one-off Alembic migration, the
IncidentFlow API, the investigation worker, ElasticMQ (a local SQS-compatible queue), the React
web application, and Keycloak on one local Docker network. It is intended for local validation,
not an AWS deployment.

## Configure local secrets

Copy the two templates without committing the resulting `.env` files:

```powershell
Copy-Item .env.example .env
Copy-Item apps/api/.env.example apps/api/.env
```

Replace the Keycloak and OpenAI placeholders. Keep
`POSTGRES_PASSWORD=incidentflow_dev` when reusing the existing local
PostgreSQL volume. PostgreSQL stores its initial password inside that volume,
so changing the Compose value later does not rotate it. `OPENAI_API_KEY` is
required for the API settings, even if no investigation is started.

For a new local database, choose the password before the first `docker compose
up` and use that same value in both `.env` and `apps/api/.env`. Do not delete a
volume just to change a password unless you explicitly intend to discard its
local data and persisted checkpoints.

## Start the stack

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

The migration service exits successfully after applying `alembic upgrade head`.
ElasticMQ starts in parallel. The API then starts, opens the PostgreSQL LangGraph checkpointer,
and calls `checkpointer.setup()` for the checkpoint tables. The worker starts alongside it.

- Web application: `http://127.0.0.1:5173`
- API health: `http://127.0.0.1:8000/health`
- API readiness: `http://127.0.0.1:8000/health/ready`
- Keycloak: `http://127.0.0.1:8080`
- ElasticMQ (SQS API): `http://127.0.0.1:9324`

The web container proxies `/api/*` to the API container, so browser requests
remain same-origin.

If a Vite development server already uses port `5173`, set `WEB_PORT=5174` in
the root `.env` before starting the `web` service. The web application will
then be available at `http://127.0.0.1:5174`.

## Investigation queue and worker

Starting or resuming an investigation returns `202` with a `PENDING` row and sends
`{"investigation_id": ...}` to the `incidentflow-investigations` queue. The `worker` service
(`python -m incidentflow.worker`) claims each job, runs the workflow, and updates the row; the
dashboard polls until it finishes. Follow it with `docker compose logs -f worker`. A run that
takes longer than `JOB_TIMEOUT_SECONDS` (default 900, AWS Lambda's 15-minute cap) is cancelled
and marked `FAILED`; if it was executing an approved Jira write, the error says the Jira outcome
is unknown, so check Jira before launching again.

ElasticMQ is configured in `infra/elasticmq/elasticmq.conf`: a visibility timeout of 300 seconds
(matching `JOB_LEASE_SECONDS`) and a dead-letter queue, `incidentflow-investigations-dlq`, after 3
receives. Queue state is in memory, so it is lost when the container restarts; the worker's
sweeper re-sends `PENDING` and expired `RUNNING` rows from the database. When
`SQS_ENDPOINT_URL` is set, the queue client signs with built-in dummy credentials (`local`), so
no AWS keys are needed for ElasticMQ. Do not export `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
for the queue: they are forwarded to the CloudWatch MCP server and override its `AWS_PROFILE`.

### Running the API and worker on the host

To run `uvicorn` and the worker outside Docker against the Compose queue, start only ElasticMQ and
point both processes at it (in each shell, or in `apps/api/.env`):

```powershell
docker compose up -d elasticmq
$env:SQS_ENDPOINT_URL = "http://127.0.0.1:9324"
$env:JOB_QUEUE_URL = "http://127.0.0.1:9324/000000000000/incidentflow-investigations"
uvicorn incidentflow.main:app --reload          # shell 1, from apps/api
python -m incidentflow.worker                   # shell 2, from apps/api
```

## Stop the stack

```powershell
docker compose down
```

Do not add `--volumes` unless you explicitly want to delete the local
PostgreSQL database and its persisted checkpoints.

## External integrations

Jira, MongoDB, GitHub, Pinecone, and CloudWatch remain disabled by default. The local MCP
servers used during development are not automatically exposed to containers.
Enable an integration only after its credentials, network path, and
least-privilege policy have been configured for Docker or AWS.

The CloudWatch MCP server is built into the API image. AWS credentials are mounted only with the
opt-in override file; see [cloudwatch-agent.md](cloudwatch-agent.md#docker-compose):

```powershell
docker compose -f docker-compose.yml -f docker-compose.cloudwatch.yml up --build -d
```

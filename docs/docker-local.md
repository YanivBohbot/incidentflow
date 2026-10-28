# Local Docker environment

This Compose environment runs PostgreSQL, the one-off Alembic migration, the
IncidentFlow API, the React web application, and Keycloak on one local Docker
network. It is intended for local validation, not an AWS deployment.

## Configure local secrets

Copy the two templates without committing the resulting `.env` files:

```powershell
Copy-Item .env.example .env
Copy-Item apps/api/.env.example apps/api/.env
```

Replace every `CHANGE_ME` value. `POSTGRES_PASSWORD` must be identical in both
files. `OPENAI_API_KEY` is required for the API settings, even if no
investigation is started.

## Start the stack

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

The migration service exits successfully after applying `alembic upgrade head`.
The API then starts, opens the PostgreSQL LangGraph checkpointer, and calls
`checkpointer.setup()` for the checkpoint tables.

- Web application: `http://127.0.0.1:5173`
- API health: `http://127.0.0.1:8000/health`
- API readiness: `http://127.0.0.1:8000/health/ready`
- Keycloak: `http://127.0.0.1:8080`

The web container proxies `/api/*` to the API container, so browser requests
remain same-origin.

## Stop the stack

```powershell
docker compose down
```

Do not add `--volumes` unless you explicitly want to delete the local
PostgreSQL database and its persisted checkpoints.

## External integrations

Jira, MongoDB, GitHub, and Pinecone remain disabled by default. The local MCP
servers used during development are not automatically exposed to containers.
Enable an integration only after its credentials, network path, and
least-privilege policy have been configured for Docker or AWS.

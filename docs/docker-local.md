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
The API then starts, opens the PostgreSQL LangGraph checkpointer, and calls
`checkpointer.setup()` for the checkpoint tables.

- Web application: `http://127.0.0.1:5173`
- API health: `http://127.0.0.1:8000/health`
- API readiness: `http://127.0.0.1:8000/health/ready`
- Keycloak: `http://127.0.0.1:8080`

The web container proxies `/api/*` to the API container, so browser requests
remain same-origin.

If a Vite development server already uses port `5173`, set `WEB_PORT=5174` in
the root `.env` before starting the `web` service. The web application will
then be available at `http://127.0.0.1:5174`.

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

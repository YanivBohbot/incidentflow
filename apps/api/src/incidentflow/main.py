import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request

from incidentflow.agent.orchestration.checkpoints.postgres import open_postgres_checkpointer
from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.api.routes.demo import router as demo_router
from incidentflow.api.routes.incidents import (
    router as incidents_router,
)
from incidentflow.api.routes.investigations import router as investigations_router
from incidentflow.application.jobs.queue import JobQueue
from incidentflow.core.config import Settings, get_settings
from incidentflow.core.operational_metrics import OperationalMetrics
from incidentflow.core.ssm import load_ssm_secrets_if_configured
from incidentflow.infrastructure.database.investigation_repository import InvestigationRepository
from incidentflow.infrastructure.database.session import SessionLocal
from incidentflow.infrastructure.queue.sqs import build_job_queue

logger = logging.getLogger(__name__)


def create_app(
    *,
    checkpointer_context_factory: Callable[[str], AbstractAsyncContextManager[Any]] = (
        open_postgres_checkpointer
    ),
    job_queue_factory: Callable[[Settings], JobQueue] = build_job_queue,
) -> FastAPI:
    settings = get_settings()
    if settings.auth_enabled and not (settings.oidc_issuer_url and settings.oidc_client_id):
        raise RuntimeError("AUTH_ENABLED=true requires OIDC_ISSUER_URL and OIDC_CLIENT_ID.")
    operational_metrics = OperationalMetrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Checkpoint tables are created by `python -m incidentflow.migrate`, not per instance.
        async with checkpointer_context_factory(settings.checkpoint_database_url) as checkpointer:
            app.state.job_queue = job_queue_factory(settings)
            supervisor = build_investigation_supervisor()
            app.state.investigation_workflow = build_investigation_workflow(
                supervisor,
                checkpointer=checkpointer,
            )
            yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI-Powered Incident Management Platform",
        lifespan=lifespan,
    )
    app.state.operational_metrics = operational_metrics

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        """Attach a correlation ID and aggregate only the request response status."""
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            operational_metrics.record_request(500)
            raise
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(round((perf_counter() - started_at) * 1000))
        operational_metrics.record_request(response.status_code)
        return response

    @app.get("/health", tags=["System"])
    def health() -> dict[str, str]:
        """Confirm that the HTTP process is running."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["System"])
    def readiness() -> dict[str, str]:
        """Confirm that lifespan startup created the durable workflow dependencies."""
        if not hasattr(app.state, "investigation_workflow"):
            return {"status": "starting"}
        return {"status": "ready", "checkpointer": "ready"}

    @app.get("/operations/metrics", tags=["System"])
    def metrics() -> dict[str, dict[str, int]]:
        """Expose aggregated counters without request payloads or external evidence."""
        with SessionLocal() as session:
            by_lifecycle = InvestigationRepository(session).count_by_lifecycle()
        return {**operational_metrics.snapshot(), "investigations_by_lifecycle": by_lifecycle}

    app.include_router(
        incidents_router,
        prefix=settings.api_prefix,
    )
    app.include_router(investigations_router, prefix=settings.api_prefix)
    app.include_router(demo_router, prefix=settings.api_prefix)
    return app


# On AWS the api Lambda (uvicorn behind Lambda Web Adapter) reads its secrets from SSM first.
load_ssm_secrets_if_configured()
app = create_app()

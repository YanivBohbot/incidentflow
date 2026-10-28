from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from typing import Any

from fastapi import FastAPI

from incidentflow.agent.orchestration.checkpoints import open_postgres_checkpointer
from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.agent.orchestration.jira_action_workflow import build_jira_action_workflow
from incidentflow.api.routes.incidents import (
    router as incidents_router,
)
from incidentflow.api.routes.investigations import router as investigations_router
from incidentflow.api.routes.jira import router as jira_router
from incidentflow.core.config import get_settings


def create_app(
    *,
    checkpointer_context_factory: Callable[[str], AbstractContextManager[Any]] = (
        open_postgres_checkpointer
    ),
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with checkpointer_context_factory(settings.checkpoint_database_url) as checkpointer:
            checkpointer.setup()
            app.state.investigation_workflow = build_investigation_workflow(
                checkpointer=checkpointer
            )
            app.state.jira_action_workflow = build_jira_action_workflow(
                checkpointer=checkpointer
            )
            yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI-Powered Incident Management Platform",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["System"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(
        incidents_router,
        prefix=settings.api_prefix,
    )
    app.include_router(investigations_router, prefix=settings.api_prefix)
    app.include_router(jira_router, prefix=settings.api_prefix)

    return app


app = create_app()

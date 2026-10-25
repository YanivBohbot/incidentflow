from fastapi import FastAPI

from incidentflow.api.routes.incidents import (
    router as incidents_router,
)
from incidentflow.api.routes.investigations import router as investigations_router
from incidentflow.api.routes.jira import router as jira_router
from incidentflow.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI-Powered Incident Management Platform",
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

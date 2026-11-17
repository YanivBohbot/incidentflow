"""API contracts of the demo endpoints."""

from pydantic import BaseModel


class DemoStatus(BaseModel):
    enabled: bool


class DemoRunStarted(BaseModel):
    started: bool
    run_id: str | None = None
    closed_incidents: int = 0

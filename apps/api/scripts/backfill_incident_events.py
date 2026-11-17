"""Reconstruct incident events for data created before the history existed (run once).

Usage (inside the api container, or on the host with DATABASE_URL set):
    python scripts/backfill_incident_events.py

Review decisions are read from each investigation's trace through the running app, so the
LangGraph checkpointer must be reachable. Incidents that already have events are skipped,
so running the script again inserts nothing.
"""

import sys
from uuid import UUID

from fastapi.testclient import TestClient

from incidentflow.application.history_backfill import backfill
from incidentflow.core.auth import LOCAL_PRINCIPAL, get_principal
from incidentflow.core.config import get_settings
from incidentflow.domain.investigations.models import InvestigationTraceStep
from incidentflow.infrastructure.database.session import SessionLocal
from incidentflow.main import create_app


def main() -> int:
    """Open the app for trace reads, backfill every incident without events, print the count."""
    app = create_app()
    app.dependency_overrides[get_principal] = lambda: LOCAL_PRINCIPAL
    prefix = get_settings().api_prefix
    with TestClient(app) as client:

        def read_trace(investigation_id: UUID) -> list[InvestigationTraceStep]:
            response = client.get(f"{prefix}/investigations/{investigation_id}/trace")
            if response.status_code != 200:
                return []
            return [InvestigationTraceStep.model_validate(step) for step in response.json()]

        with SessionLocal() as session:
            inserted = backfill(session, trace_reader=read_trace)
    print(f"Reconstructed {inserted} incident events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

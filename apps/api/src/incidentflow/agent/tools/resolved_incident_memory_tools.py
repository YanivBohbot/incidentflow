"""Read-only tool for retrieving approved lessons from earlier incidents."""

import json

from langchain.tools import tool

from incidentflow.core.config import get_settings
from incidentflow.knowledge.resolved_incident_store import ResolvedIncidentStore


@tool(
    "search_confirmed_incidents",
    description=(
        "Search read-only, operator-confirmed lessons from completed incidents. "
        "Requires a service and environment scope; never returns raw incident evidence."
    ),
)
def search_confirmed_incidents(
    query: str,
    service: str,
    environment: str,
    tenant_id: str | None = None,
) -> str:
    """Return scoped historical lessons with source-investigation citations."""
    store = ResolvedIncidentStore.from_settings(get_settings())
    matches = store.search_confirmed_incidents(
        query,
        service=service,
        environment=environment,
        tenant_id=tenant_id,
    )
    return json.dumps(
        {
            "source_status": "live",
            "query": query,
            "scope": {
                "service": service,
                "environment": environment,
                "tenant_id": tenant_id,
            },
            "matches": [
                {
                    "source_investigation_id": document.metadata.get("investigation_id"),
                    "service": document.metadata.get("service"),
                    "environment": document.metadata.get("environment"),
                    "score": score,
                    "lesson": document.page_content,
                }
                for document, score in matches
            ],
        }
    )

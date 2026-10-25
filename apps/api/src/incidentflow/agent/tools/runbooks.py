import json

from langchain.tools import tool
from langchain_core.tools import BaseTool

from incidentflow.core.config import get_settings
from incidentflow.knowledge.pinecone_store import PineconeKnowledgeStore


@tool("search_incident_response_guides")
def search_simulated_incident_response_guides(query: str) -> str:
    """Search simulated incident response guides for development-only testing.

    This development adapter is read-only and returns simulated Pinecone retrieval
    results. Use it to find runbook guidance relevant to an incident description.
    """
    return (
        "SIMULATED DATA - Not retrieved from Pinecone or an internal document store. "
        f"Query: {query}. "
        "Document: RUNBOOK-PAYMENTS-DB-001, title: Payment API database pool exhaustion. "
        "Guidance: verify database saturation and pool metrics; identify long-running "
        "queries; temporarily reduce non-critical traffic only through the approved "
        "change process; record the incident timeline. "
        "Document: RUNBOOK-INCIDENT-TRIAGE-002, title: Evidence-based incident triage. "
        "Guidance: retain source references and label recommendations separately from "
        "observed evidence."
    )


@tool("search_incident_response_guides")
def search_incident_response_guides(
    query: str,
    document_id: str | None = None,
    source_kind: str | None = None,
) -> str:
    """Retrieve grounded excerpts from the configured Pinecone incident response guides.

    This tool is read-only. It returns document identifiers, official source URLs,
    chunk offsets, relevance scores, and excerpts needed for cited recommendations.
    """
    settings = get_settings()
    store = PineconeKnowledgeStore.from_settings(settings)
    metadata_filter = {}
    if document_id:
        metadata_filter["document_id"] = document_id
    if source_kind:
        metadata_filter["source_kind"] = source_kind
    matches = store.search(query, metadata_filter=metadata_filter or None)
    return json.dumps(
        {
            "source_status": "live",
            "query": query,
            "metadata_filter": metadata_filter or None,
            "matches": [
                {
                    "document_id": document.metadata.get("document_id"),
                    "title": document.metadata.get("title"),
                    "source_url": document.metadata.get("source_url"),
                    "knowledge_namespace": document.metadata.get("knowledge_namespace"),
                    "start_index": document.metadata.get("start_index"),
                    "score": score,
                    "excerpt": document.page_content,
                }
                for document, score in matches
            ],
        }
    )


def build_knowledge_tools() -> list[BaseTool]:
    """Expose live Pinecone retrieval only after explicit configuration."""
    if get_settings().pinecone_enabled:
        return [search_incident_response_guides]
    return [search_simulated_incident_response_guides]

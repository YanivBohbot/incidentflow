import json
from uuid import uuid4

from langchain_core.documents import Document

from incidentflow.agent.tools.resolved_incident_memory_tools import (
    search_confirmed_incidents,
)
from incidentflow.domain.memory.models import IncidentLesson, IncidentLessonState
from incidentflow.knowledge.resolved_incident_store import ResolvedIncidentStore


class _FakeKnowledgeStore:
    def __init__(self) -> None:
        self.added_documents: list[Document] = []
        self.search_filters: list[dict] = []

    def add_documents(self, documents: list[Document]) -> list[str]:
        self.added_documents.extend(documents)
        return ["resolved-incident:123"]

    def search(self, _query: str, metadata_filter: dict):
        self.search_filters.append(metadata_filter)
        return [
            (
                Document(
                    page_content="Use bounded connection pooling.",
                    metadata={"investigation_id": "incident-123", "service": "payment-api"},
                ),
                0.91,
            )
        ]


def test_search_confirmed_incidents_filters_by_service_environment_and_tenant() -> None:
    knowledge_store = _FakeKnowledgeStore()
    store = ResolvedIncidentStore(knowledge_store)

    matches = store.search_confirmed_incidents(
        "payment connection pool exhaustion",
        service="payment-api",
        environment="production",
        tenant_id="tenant-a",
    )

    assert len(matches) == 1
    assert knowledge_store.search_filters == [
        {
            "approval_status": "CONFIRMED",
            "service": "payment-api",
            "environment": "production",
            "tenant_scope": {"$in": ["tenant-a", "global"]},
        }
    ]


def test_indexed_lesson_contains_only_confirmed_summary_fields() -> None:
    knowledge_store = _FakeKnowledgeStore()
    store = ResolvedIncidentStore(knowledge_store)
    lesson = IncidentLesson(
        investigation_id=uuid4(),
        service="payment-api",
        environment="production",
        confirmed_root_cause="Connection pool exhaustion.",
        validated_resolution="Bound the pool and optimize long-running queries.",
        state=IncidentLessonState.PENDING_INDEX,
    )

    vector_id = store.index_confirmed_incident_lesson(lesson)

    assert vector_id == "resolved-incident:123"
    assert knowledge_store.added_documents[0].metadata == {
        "investigation_id": str(lesson.investigation_id),
        "service": "payment-api",
        "environment": "production",
        "tenant_scope": "global",
        "approval_status": "CONFIRMED",
    }
    assert knowledge_store.added_documents[0].page_content == (
        "Confirmed root cause: Connection pool exhaustion.\n"
        "Validated resolution: Bound the pool and optimize long-running queries."
    )


def test_memory_tool_returns_source_investigation_citations(monkeypatch) -> None:
    knowledge_store = _FakeKnowledgeStore()
    monkeypatch.setattr(
        "incidentflow.agent.tools.resolved_incident_memory_tools.get_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "incidentflow.agent.tools.resolved_incident_memory_tools.ResolvedIncidentStore.from_settings",
        lambda _settings: ResolvedIncidentStore(knowledge_store),
    )

    response = search_confirmed_incidents.invoke(
        {
            "query": "payment connection pool exhaustion",
            "service": "payment-api",
            "environment": "production",
            "tenant_id": "tenant-a",
        }
    )
    payload = json.loads(response)

    assert payload["source_status"] == "live"
    assert payload["matches"][0]["source_investigation_id"] == "incident-123"

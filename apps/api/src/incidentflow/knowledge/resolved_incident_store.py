"""Isolated, curated Pinecone storage for confirmed incident lessons."""

from langchain_core.documents import Document

from incidentflow.core.config import Settings
from incidentflow.domain.memory.models import IncidentLesson, IncidentLessonState
from incidentflow.knowledge.pinecone_store import PineconeKnowledgeStore


class ResolvedIncidentStore:
    """Index and retrieve only operator-curated lessons from completed incidents."""

    def __init__(self, knowledge_store: PineconeKnowledgeStore) -> None:
        """Wrap the namespace-specific Pinecone adapter used for curated lessons."""
        self._knowledge_store = knowledge_store

    @classmethod
    def from_settings(cls, settings: Settings) -> "ResolvedIncidentStore":
        """Create a store bound only to the resolved-incidents namespace."""
        knowledge_store = PineconeKnowledgeStore.from_settings(
            settings,
            namespaces=(settings.pinecone_resolved_incidents_namespace,),
        )
        return cls(knowledge_store)

    def index_confirmed_incident_lesson(self, lesson: IncidentLesson) -> str:
        """Index an eligible lesson; the repository marks it confirmed only after success."""
        if lesson.state is not IncidentLessonState.PENDING_INDEX:
            raise ValueError("Only pending incident lessons are eligible for indexing.")

        document = Document(
            page_content=(
                f"Confirmed root cause: {lesson.confirmed_root_cause}\n"
                f"Validated resolution: {lesson.validated_resolution}"
            ),
            metadata={
                "investigation_id": str(lesson.investigation_id),
                "service": lesson.service,
                "environment": lesson.environment,
                "tenant_scope": lesson.tenant_id or "global",
                "approval_status": "CONFIRMED",
            },
        )
        return self._knowledge_store.add_documents([document])[0]

    def search_confirmed_incidents(
        self,
        query: str,
        *,
        service: str,
        environment: str,
        tenant_id: str | None = None,
    ):
        """Search confirmed lessons within mandatory service, environment, and tenant scope."""
        tenant_scopes = [tenant_id, "global"] if tenant_id else ["global"]
        metadata_filter = {
            "approval_status": "CONFIRMED",
            "service": service,
            "environment": environment,
            "tenant_scope": {"$in": tenant_scopes},
        }
        return self._knowledge_store.search(query, metadata_filter=metadata_filter)

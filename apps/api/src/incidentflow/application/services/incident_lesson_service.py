"""Explicit operator-confirmation workflow for long-term incident lessons."""

from typing import Protocol

from incidentflow.domain.history.models import IncidentEventKind
from incidentflow.domain.memory.models import IncidentLesson, IncidentLessonConfirmation
from incidentflow.infrastructure.database.incident_event_repository import (
    IncidentEventRepository,
)
from incidentflow.infrastructure.database.incident_lesson_repository import IncidentLessonRepository


class IncidentLessonIndexer(Protocol):
    """The narrow write contract for the isolated resolved-incident namespace."""

    def index_confirmed_incident_lesson(self, lesson: IncidentLesson) -> str:
        """Write the curated lesson and return the resulting vector identifier."""
        ...


class IncidentLessonService:
    """Persist a reviewed lesson, then confirm it only after Pinecone indexing succeeds."""

    def __init__(
        self,
        repository: IncidentLessonRepository,
        indexer: IncidentLessonIndexer,
        *,
        events: IncidentEventRepository | None = None,
    ) -> None:
        """Keep the persistence and isolated-vector-store boundaries for confirmation."""
        self._repository = repository
        self._indexer = indexer
        self._events = events

    def confirm_and_index(
        self, confirmation: IncidentLessonConfirmation, *, actor: str = "system"
    ) -> IncidentLesson:
        """Save the operator's confirmed lesson and index it in Pinecone for future investigations."""
        lesson = self._repository.create_pending(confirmation)
        try:
            vector_id = self._indexer.index_confirmed_incident_lesson(lesson)
        except Exception as error:
            failed_lesson = self._repository.mark_index_failed(lesson.id, str(error))
            if failed_lesson is None:
                raise RuntimeError("Unable to record the incident lesson indexing failure.") from error
            return failed_lesson

        confirmed_lesson = self._repository.mark_confirmed(lesson.id, vector_id)
        if confirmed_lesson is None:
            raise RuntimeError("Unable to confirm the indexed incident lesson.")
        if self._events is not None:
            self._events.record(
                IncidentEventKind.LESSON_SAVED,
                incident_id=self._repository.incident_id_for(confirmation.investigation_id),
                investigation_id=confirmation.investigation_id,
                actor=actor,
                summary=f"Lesson saved to memory by {actor}",
                details={"service": confirmation.service},
            )
        return confirmed_lesson

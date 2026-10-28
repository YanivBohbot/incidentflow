from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from incidentflow.domain.investigations.models import InvestigationLifecycle
from incidentflow.domain.memory.models import (
    IncidentLesson,
    IncidentLessonConfirmation,
    IncidentLessonState,
)
from incidentflow.infrastructure.database.models import IncidentLessonORM, InvestigationORM


class IncidentLessonRepository:
    """Store only reviewed lessons from completed investigations for later indexing."""

    def __init__(self, session: Session) -> None:
        """Keep the request-scoped SQLAlchemy session used for lesson state changes."""
        self.session = session

    @staticmethod
    def to_domain(orm: IncidentLessonORM) -> IncidentLesson:
        """Convert a database row into the validated domain representation."""
        return IncidentLesson.model_validate(
            {
                "id": orm.id,
                "investigation_id": orm.investigation_id,
                "service": orm.service,
                "environment": orm.environment,
                "tenant_id": orm.tenant_id,
                "confirmed_root_cause": orm.confirmed_root_cause,
                "validated_resolution": orm.validated_resolution,
                "state": orm.state,
                "vector_id": orm.vector_id,
                "index_error": orm.index_error,
                "created_at": orm.created_at,
                "confirmed_at": orm.confirmed_at,
                "updated_at": orm.updated_at,
            }
        )

    def create_pending(self, confirmation: IncidentLessonConfirmation) -> IncidentLesson:
        """Create an index-eligible lesson only for a completed investigation."""
        investigation = self.session.get(InvestigationORM, confirmation.investigation_id)
        if investigation is None or investigation.lifecycle is not InvestigationLifecycle.COMPLETED:
            raise ValueError("A confirmed lesson requires a completed investigation.")

        lesson = IncidentLessonORM(
            investigation_id=confirmation.investigation_id,
            service=confirmation.service,
            environment=confirmation.environment,
            tenant_id=confirmation.tenant_id,
            confirmed_root_cause=confirmation.confirmed_root_cause,
            validated_resolution=confirmation.validated_resolution,
        )
        self.session.add(lesson)
        self.session.commit()
        self.session.refresh(lesson)
        return self.to_domain(lesson)

    def get(self, lesson_id: UUID) -> IncidentLesson | None:
        """Load one persisted lesson when it exists."""
        lesson = self.session.get(IncidentLessonORM, lesson_id)
        return self.to_domain(lesson) if lesson is not None else None

    def mark_confirmed(self, lesson_id: UUID, vector_id: str) -> IncidentLesson | None:
        """Mark a pending lesson confirmed after its Pinecone write succeeds."""
        lesson = self.session.get(IncidentLessonORM, lesson_id, with_for_update=True)
        if lesson is None or lesson.state is not IncidentLessonState.PENDING_INDEX:
            self.session.rollback()
            return None

        lesson.state = IncidentLessonState.CONFIRMED
        lesson.vector_id = vector_id
        lesson.index_error = None
        lesson.confirmed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(lesson)
        return self.to_domain(lesson)

    def mark_index_failed(self, lesson_id: UUID, error_message: str) -> IncidentLesson | None:
        """Record a failed Pinecone write without exposing the lesson to retrieval."""
        lesson = self.session.get(IncidentLessonORM, lesson_id, with_for_update=True)
        if lesson is None or lesson.state is not IncidentLessonState.PENDING_INDEX:
            self.session.rollback()
            return None

        lesson.state = IncidentLessonState.INDEX_FAILED
        lesson.index_error = error_message
        self.session.commit()
        self.session.refresh(lesson)
        return self.to_domain(lesson)

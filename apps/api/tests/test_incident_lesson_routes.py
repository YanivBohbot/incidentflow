from uuid import uuid4

from incidentflow.api.routes.investigations import confirm_incident_lesson
from incidentflow.domain.memory.models import (
    IncidentLesson,
    IncidentLessonConfirmation,
    IncidentLessonState,
)


def test_confirm_incident_lesson_uses_the_explicit_operator_input() -> None:
    investigation_id = uuid4()
    request = IncidentLessonConfirmation(
        investigation_id=investigation_id,
        service="payment-api",
        environment="production",
        confirmed_root_cause="Connection pool exhaustion.",
        validated_resolution="Bound the pool and optimize long-running queries.",
    )
    expected = IncidentLesson(
        **request.model_dump(),
        state=IncidentLessonState.CONFIRMED,
        vector_id="resolved-incident:123",
    )

    class FakeInvestigationService:
        def get_investigation(self, requested_id):
            return object() if requested_id == investigation_id else None

    class FakeLessonService:
        def confirm_and_index(self, confirmation):
            assert confirmation == request
            return expected

    lesson = confirm_incident_lesson(
        investigation_id,
        request,
        FakeInvestigationService(),
        FakeLessonService(),
    )

    assert lesson == expected

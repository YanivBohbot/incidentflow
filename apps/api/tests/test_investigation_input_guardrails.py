from incidentflow.agent.orchestration.investigation_workflow import (
    validate_incident_request,
)


def test_overlong_incident_request_fails_before_supervisor_execution() -> None:
    result = validate_incident_request(
        {"incident_request": "x" * 5001, "incident_business_status": "OPEN"}
    )

    assert result["investigation_lifecycle"] == "failed"
    assert result["errors"] == ["incident_request must not exceed 5000 characters."]

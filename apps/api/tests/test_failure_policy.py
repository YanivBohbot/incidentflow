from incidentflow.agent.orchestration.fault_tolerance.failure_policy import (
    classify_node_failure,
)


def test_timeout_becomes_safe_external_source_failure() -> None:
    failure = classify_node_failure(
        "supervisor_investigation",
        TimeoutError("mongodb://operator:secret@internal.example"),
    )

    assert failure.code == "EXTERNAL_SOURCE_UNAVAILABLE"
    assert failure.node == "supervisor_investigation"
    assert failure.retryable is True
    assert "secret" not in failure.message

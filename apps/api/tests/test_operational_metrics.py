from incidentflow.core.operational_metrics import OperationalMetrics


def test_operational_metrics_expose_only_aggregated_counts() -> None:
    metrics = OperationalMetrics()

    metrics.record_request(200)
    metrics.record_request(200)
    metrics.record_request(503)
    metrics.record_investigation("COMPLETED")
    metrics.record_investigation("FAILED")

    assert metrics.snapshot() == {
        "requests_by_status": {"200": 2, "503": 1},
        "investigations_by_lifecycle": {"COMPLETED": 1, "FAILED": 1},
    }

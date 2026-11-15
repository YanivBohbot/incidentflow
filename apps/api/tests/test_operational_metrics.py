from incidentflow.core.operational_metrics import OperationalMetrics


def test_operational_metrics_expose_only_aggregated_counts() -> None:
    metrics = OperationalMetrics()

    metrics.record_request(200)
    metrics.record_request(200)
    metrics.record_request(503)

    assert metrics.snapshot() == {"requests_by_status": {"200": 2, "503": 1}}

from incidentflow.demo.scenarios import (
    DEMO_ALARM_NAMES,
    LEGACY_ALARM_NAMES,
    METRIC_NAMESPACE,
    SCENARIOS,
)
from incidentflow.domain.incidents.models import IncidentPriority


def test_scenarios_cover_the_eight_demo_services() -> None:
    assert [s.alarm_name for s in SCENARIOS] == [
        "if-checkout",
        "if-orders",
        "if-auth",
        "if-inventory",
        "if-refunds",
        "if-payments",
        "if-search",
        "if-notifications",
    ]
    assert DEMO_ALARM_NAMES == tuple(s.alarm_name for s in SCENARIOS)


def test_scenario_texts_fit_incident_and_alarm_limits() -> None:
    for s in SCENARIOS:
        assert 5 <= len(s.title) <= 200 and len(s.title) <= 256
        assert 10 <= len(s.description) <= 1024


def test_scenarios_start_with_critical_outages() -> None:
    assert SCENARIOS[0].priority is IncidentPriority.CRITICAL


def test_legacy_alarm_names_and_namespace_are_kept_for_cleanup() -> None:
    assert "incidentflow-demo-payment-5xx" in LEGACY_ALARM_NAMES
    assert "incidentflow-demo-checkout-api" in LEGACY_ALARM_NAMES
    assert len(LEGACY_ALARM_NAMES) == 8
    assert METRIC_NAMESPACE == "IncidentFlow/Demo"
    assert SCENARIOS[0].log_group == "/incidentflow/demo/checkout-api"

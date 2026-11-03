import re

from incidentflow.agent.tools.data_intelligence_tools import (
    EVENT_LIMIT,
    events_pipeline,
    service_name_pattern,
)


def test_service_pattern_matches_naming_variants_of_one_service_only() -> None:
    pattern = service_name_pattern("payment-service")

    for name in ("payment-api", "payment-service", "Payment API", "payment"):
        assert re.match(pattern, name, re.IGNORECASE), name
    for name in ("payments-api", "checkout-api", "payment-gateway"):
        assert not re.match(pattern, name, re.IGNORECASE), name


def test_events_query_filters_on_the_named_service_and_keeps_the_latest_events() -> None:
    pipeline = events_pipeline("inventory-service")

    assert pipeline[0]["$match"]["service"]["$regex"] == service_name_pattern("inventory-service")
    # Newest first to keep the latest events, then back to a readable time order.
    assert pipeline[1:] == [
        {"$sort": {"timestamp": -1}},
        {"$limit": EVENT_LIMIT},
        {"$sort": {"timestamp": 1}},
    ]


def test_events_query_without_service_returns_the_most_recent_events() -> None:
    assert "$match" not in str(events_pipeline(None))

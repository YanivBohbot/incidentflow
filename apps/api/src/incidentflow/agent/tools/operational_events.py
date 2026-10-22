from langchain.tools import tool


@tool
def search_operational_events(service_name: str) -> str:
    """Search operational events for a service.

    This development adapter is read-only and returns simulated MongoDB events.
    """
    return (
        "SIMULATED DATA - Not retrieved from MongoDB. "
        f"Service: {service_name}. "
        "09:05 UTC: HTTP 500 rate increased from 0.2% to 18.7%. "
        "09:07 UTC: database pool timeout errors appeared. "
        "09:12 UTC: active connections reached the configured limit."
    )

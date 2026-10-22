from langchain.tools import tool


@tool
def search_incident_tickets(service_name: str) -> str:
    """Search historical IT incident tickets for a service.

    This development adapter is read-only and returns simulated Jira data.
    """
    return (
        "SIMULATED DATA - Not retrieved from Jira. "
        f"Service: {service_name}. "
        "Ticket INC-104: Payment API HTTP 500 errors. "
        "Previous suspected cause: exhausted database connections."
    )

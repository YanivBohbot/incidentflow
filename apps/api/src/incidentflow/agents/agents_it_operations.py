from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from incidentflow.agents.models import ITOperationsFinding
from incidentflow.core.config import get_settings


@tool
def search_incident_tickets(service_name: str) -> str:
    """Search existing IT incident tickets for a service."""
    return (
        "SIMULATED DATA - Not retrieved from Jira. "
        f"Service: {service_name}. "
        "Ticket INC-104: Payment API HTTP 500 errors. "
        "Previous suspected cause: exhausted database connections."
    )


def build_it_operations_agent():
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=[search_incident_tickets],
        system_prompt=(
            "You are IncidentFlow's IT Operations Agent. "
            "Investigate IT incidents using available tools. "
            "Never claim simulated data is real Jira data. "
            "Distinguish confirmed facts from hypotheses. "
            "Do not perform any write operation. "
            "Return the required structured finding after using relevant tools."
        ),
        name="it_operations_agent",
        response_format=ITOperationsFinding,
    )

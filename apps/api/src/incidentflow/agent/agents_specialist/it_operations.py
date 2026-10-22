from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import ITOperationsFinding
from incidentflow.agent.identities import IT_OPERATIONS_AGENT
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.it_operations import IT_OPERATIONS_SYSTEM_PROMPT
from incidentflow.agent.tools.jira import search_incident_tickets
from incidentflow.core.config import get_settings


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
        system_prompt=IT_OPERATIONS_SYSTEM_PROMPT,
        name=IT_OPERATIONS_AGENT.technical_name,
        middleware=build_shared_middleware(),
        response_format=ITOperationsFinding,
    )

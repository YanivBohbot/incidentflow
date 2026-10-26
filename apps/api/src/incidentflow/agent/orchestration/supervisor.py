from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
from incidentflow.agent.tools.specialist_delegation import (
    ask_data_intelligence,
    ask_github,
    ask_it_operations,
    ask_knowledge,
)
from incidentflow.core.config import get_settings


def build_investigation_supervisor():
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=[ask_it_operations, ask_data_intelligence, ask_knowledge, ask_github],
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        name=INVESTIGATION_SUPERVISOR.technical_name,
        middleware=build_shared_middleware(),
        response_format=InvestigationReport,
    )

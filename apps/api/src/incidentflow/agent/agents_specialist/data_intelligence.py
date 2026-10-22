from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import DataIntelligenceFinding
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.data_intelligence import DATA_INTELLIGENCE_SYSTEM_PROMPT
from incidentflow.agent.tools.operational_events import search_operational_events
from incidentflow.core.config import get_settings


def build_data_intelligence_agent():
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=[search_operational_events],
        system_prompt=DATA_INTELLIGENCE_SYSTEM_PROMPT,
        name=DATA_INTELLIGENCE_AGENT.technical_name,
        middleware=build_shared_middleware(),
        response_format=DataIntelligenceFinding,
    )

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import KnowledgeFinding
from incidentflow.agent.identities import KNOWLEDGE_AGENT
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.knowledge import KNOWLEDGE_SYSTEM_PROMPT
from incidentflow.agent.tools.runbooks import build_knowledge_tools
from incidentflow.core.config import get_settings


def build_knowledge_agent(knowledge_tools: list[BaseTool] | None = None):
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=knowledge_tools or build_knowledge_tools(),
        system_prompt=KNOWLEDGE_SYSTEM_PROMPT,
        name=KNOWLEDGE_AGENT.technical_name,
        middleware=build_shared_middleware(),
        response_format=KnowledgeFinding,
    )

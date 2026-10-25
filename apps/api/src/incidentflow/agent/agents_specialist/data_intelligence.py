from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import DataIntelligenceFinding
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.data_intelligence import DATA_INTELLIGENCE_SYSTEM_PROMPT
from incidentflow.core.config import get_settings


def build_data_intelligence_middleware() -> list[AgentMiddleware]:
    """Guard the MongoDB investigation against redundant external queries."""
    return [
        *build_shared_middleware(),
        ToolCallLimitMiddleware(
            tool_name="collection-schema",
            run_limit=1,
            exit_behavior="end",
        ),
        ToolCallLimitMiddleware(
            tool_name="aggregate",
            run_limit=1,
            exit_behavior="end",
        ),
        ToolCallLimitMiddleware(
            tool_name="find",
            run_limit=1,
            exit_behavior="end",
        ),
    ]


def build_data_intelligence_agent(mongodb_tools: list[BaseTool]):
    """Build the agent from an explicitly approved MongoDB MCP tool set."""
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=mongodb_tools,
        system_prompt=DATA_INTELLIGENCE_SYSTEM_PROMPT.format(
            database=settings.mongodb_mcp_database,
            events_collection=settings.mongodb_mcp_events_collection,
        ),
        name=DATA_INTELLIGENCE_AGENT.technical_name,
        middleware=build_data_intelligence_middleware(),
        response_format=ToolStrategy(DataIntelligenceFinding),
    )

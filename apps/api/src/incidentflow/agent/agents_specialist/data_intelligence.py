from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from incidentflow.agent.findings import DataIntelligenceFinding
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.agent.middleware import TruncateToolOutputMiddleware, build_shared_middleware
from incidentflow.agent.prompts.data_intelligence import DATA_INTELLIGENCE_SYSTEM_PROMPT
from incidentflow.core.config import get_settings


def build_data_intelligence_middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    """Guard the MongoDB investigation against redundant external queries."""
    return [
        *build_shared_middleware(),
        TruncateToolOutputMiddleware(max_characters=8000),
        ToolCallLimitMiddleware(
            tool_name="collection-schema",
            run_limit=1,
            exit_behavior="continue",
        ),
        ToolCallLimitMiddleware(
            tool_name="aggregate",
            run_limit=1,
            exit_behavior="continue",
        ),
        ToolCallLimitMiddleware(
            tool_name="find",
            run_limit=1,
            exit_behavior="continue",
        ),
        # Schema discovery, one evidence query, interpretation, and the
        # structured response should fit in five model turns.  The explicit
        # ceiling makes a malformed MCP reply fail safely instead of consuming
        # the graph recursion budget in a retry loop.
        ModelCallLimitMiddleware(run_limit=5, exit_behavior="end"),
    ]


def build_data_intelligence_agent(mongodb_tools: list[BaseTool]):
    """Build the agent from an explicitly approved MongoDB MCP tool set."""
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=settings.openai_timeout_seconds,
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


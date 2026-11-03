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

from incidentflow.agent.findings import KnowledgeFinding
from incidentflow.agent.identities import KNOWLEDGE_AGENT
from incidentflow.agent.middleware import TruncateToolOutputMiddleware, build_shared_middleware
from incidentflow.agent.prompts.knowledge import KNOWLEDGE_SYSTEM_PROMPT
from incidentflow.agent.tools.incident_response_guide_tools import build_knowledge_tools
from incidentflow.core.config import get_settings


def build_knowledge_middleware() -> list[AgentMiddleware[Any, Any, Any]]:
    """Bound retrieval: a runbook search, a confirmed-lesson search, and one refinement."""
    return [
        *build_shared_middleware(),
        TruncateToolOutputMiddleware(max_characters=8000),
        ToolCallLimitMiddleware(run_limit=3, exit_behavior="continue"),
        # Searches, then the structured finding, plus one corrective turn.
        ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
    ]


def build_knowledge_agent(knowledge_tools: list[BaseTool] | None = None):
    """Build the read-only Knowledge specialist over Pinecone retrieval tools."""
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=settings.openai_timeout_seconds,
    )

    return create_agent(
        model=model,
        tools=knowledge_tools or build_knowledge_tools(),
        system_prompt=KNOWLEDGE_SYSTEM_PROMPT,
        name=KNOWLEDGE_AGENT.technical_name,
        middleware=build_knowledge_middleware(),
        response_format=ToolStrategy(KnowledgeFinding),
    )

"""Builds the Investigation Supervisor that delegates to specialists and writes the report."""

import logging
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    LLMToolSelectorMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from incidentflow.agent.findings import InvestigationReport
from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
from incidentflow.agent.tools.cloudwatch_tools import ask_cloudwatch
from incidentflow.agent.tools.data_intelligence_tools import ask_data_intelligence
from incidentflow.agent.tools.github_tools import ask_github
from incidentflow.agent.tools.it_operations_tools import ask_it_operations
from incidentflow.agent.tools.knowledge_tools import ask_knowledge
from incidentflow.core.config import get_settings

DELEGATION_TOOLS: tuple[BaseTool, ...] = (
    ask_it_operations,
    ask_data_intelligence,
    ask_knowledge,
    ask_github,
    ask_cloudwatch,
)

TOOL_SELECTION_SYSTEM_PROMPT = (
    "Select the specialist delegations necessary to investigate this incident. "
    "Select ask_it_operations for Jira ticket context, ask_data_intelligence for MongoDB "
    "operational events, ask_knowledge for similar incidents or procedures, ask_github for recent "
    "code changes, and ask_cloudwatch for production alarms, metrics, and logs such as HTTP 5xx "
    "errors or latency. "
    "Use these exact tool names; never invent another name. "
    "Select no tool when the request does not describe an incident, such as a greeting or a "
    "question about what the assistant can do. "
    "Select all relevant tools when the request requires evidence from all sources. "
    "Do not select a tool merely because it is available."
)

logger = logging.getLogger(__name__)


class TolerantToolSelectorMiddleware(LLMToolSelectorMiddleware):
    """Tool selector that drops invented tool names instead of failing the investigation.

    The selection schema is not enforced by the model provider, so the selector can return a
    name that does not exist (for example "ask_jira"). LangChain raises on it, which fails the
    whole investigation. Unknown names are dropped; when nothing valid remains, every tool stays
    available and the supervisor, still bounded by the per-tool call limits, decides.
    """

    def _process_selection_response(
        self,
        response: dict[str, Any],
        available_tools: list[BaseTool],
        valid_tool_names: list[str],
        request: Any,
        **kwargs: Any,
    ) -> Any:
        selected = list(response.get("tools", []))
        valid = [name for name in selected if name in valid_tool_names]
        invented = [name for name in selected if name not in valid_tool_names]
        if invented:
            logger.warning("Tool selector returned unknown tools %s; ignoring them", invented)
            if not valid:
                valid = list(valid_tool_names)
        return super()._process_selection_response(
            {**response, "tools": valid}, available_tools, valid_tool_names, request, **kwargs
        )


def build_supervisor_middleware(
    model: BaseChatModel | str | None = None,
) -> list[AgentMiddleware[Any, Any, Any]]:
    """Allow bounded specialist selection and retry only idempotent read delegations."""
    return [
        TolerantToolSelectorMiddleware(
            model=model,
            system_prompt=TOOL_SELECTION_SYSTEM_PROMPT,
            max_tools=5,
        ),
        ToolRetryMiddleware(
            tools=[
                "ask_it_operations",
                "ask_data_intelligence",
                "ask_knowledge",
                "ask_github",
                "ask_cloudwatch",
            ],
            max_retries=1,
            initial_delay=0.25,
            max_delay=0.5,
            retry_on=(ConnectionError, TimeoutError, OSError),
            on_failure="continue",
        ),
        *build_shared_middleware(),
        *[
            ToolCallLimitMiddleware(tool_name=tool_name, run_limit=2, exit_behavior="continue")
            for tool_name in (
                "ask_it_operations",
                "ask_data_intelligence",
                "ask_knowledge",
                "ask_github",
                "ask_cloudwatch",
            )
        ],
    ]


def build_investigation_supervisor(tools: list[BaseTool] | None = None):
    """Create the supervisor agent with its five delegation tools and safety middleware.

    Extra calls are blocked with "continue" so the supervisor still returns a report,
    and ToolStrategy sends schema errors back so it can fix an incomplete report.
    Pass ``tools`` to replace the real delegations (for example with evaluation fixtures).
    """
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=list(DELEGATION_TOOLS) if tools is None else tools,
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        name=INVESTIGATION_SUPERVISOR.technical_name,
        middleware=build_supervisor_middleware(model),
        response_format=ToolStrategy(InvestigationReport),
    )

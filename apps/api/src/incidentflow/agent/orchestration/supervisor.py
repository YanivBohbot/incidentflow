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
from langchain_openai import ChatOpenAI

from incidentflow.agent.agents_specialist.contracts import InvestigationReport
from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
from incidentflow.agent.tools.cloudwatch_tools import ask_cloudwatch
from incidentflow.agent.tools.data_intelligence_tools import ask_data_intelligence
from incidentflow.agent.tools.github_tools import ask_github
from incidentflow.agent.tools.it_operations_tools import ask_it_operations
from incidentflow.agent.tools.knowledge_tools import ask_knowledge
from incidentflow.core.config import get_settings

TOOL_SELECTION_SYSTEM_PROMPT = (
    "Select the specialist delegations necessary to investigate this incident. "
    "Select Jira for ticket context, MongoDB for operational events, knowledge for similar incidents "
    "or procedures, GitHub for recent code changes, and CloudWatch for production alarms, metrics, "
    "and logs such as HTTP 5xx errors or latency. "
    "Select all relevant tools when the request requires evidence from all sources. "
    "Do not select a tool merely because it is available."
)


def build_supervisor_middleware(
    model: BaseChatModel | str | None = None,
) -> list[AgentMiddleware[Any, Any, Any]]:
    """Allow bounded specialist selection and retry only idempotent read delegations."""
    return [
        LLMToolSelectorMiddleware(
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
            ToolCallLimitMiddleware(tool_name=tool_name, run_limit=2, exit_behavior="end")
            for tool_name in (
                "ask_it_operations",
                "ask_data_intelligence",
                "ask_knowledge",
                "ask_github",
                "ask_cloudwatch",
            )
        ],
    ]


def build_investigation_supervisor():
    settings = get_settings()

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=[
            ask_it_operations,
            ask_data_intelligence,
            ask_knowledge,
            ask_github,
            ask_cloudwatch,
        ],
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        name=INVESTIGATION_SUPERVISOR.technical_name,
        middleware=build_supervisor_middleware(model),
        # ToolStrategy returns schema-validation feedback to the supervisor so it can
        # correct an incomplete report instead of failing the full investigation.
        response_format=ToolStrategy(InvestigationReport),
    )

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    LLMToolSelectorMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
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

TOOL_SELECTION_SYSTEM_PROMPT = (
    "Select the specialist delegations necessary to investigate this incident. "
    "Select Jira for ticket context, MongoDB for operational events, knowledge for similar incidents "
    "or procedures, and GitHub for recent code changes. "
    "Select all relevant tools when the request requires evidence from all sources. "
    "Do not select a tool merely because it is available."
)


def build_supervisor_middleware(model: BaseChatModel | str | None = None) -> list[AgentMiddleware]:
    """Allow dynamic specialist selection while bounding repeated delegations."""
    return [
        LLMToolSelectorMiddleware(
            model=model,
            system_prompt=TOOL_SELECTION_SYSTEM_PROMPT,
            max_tools=4,
        ),
        *build_shared_middleware(),
        *[
            ToolCallLimitMiddleware(tool_name=tool_name, run_limit=2, exit_behavior="end")
            for tool_name in (
                "ask_it_operations",
                "ask_data_intelligence",
                "ask_knowledge",
                "ask_github",
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
        tools=[ask_it_operations, ask_data_intelligence, ask_knowledge, ask_github],
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        name=INVESTIGATION_SUPERVISOR.technical_name,
        middleware=build_supervisor_middleware(model),
        response_format=InvestigationReport,
    )

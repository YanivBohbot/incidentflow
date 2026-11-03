"""ask_knowledge: the Supervisor delegates to the Knowledge Agent (a create_agent).

The agent chooses its Pinecone searches: incident response runbooks and, when enabled,
operator-confirmed lessons from resolved incidents. It returns a KnowledgeFinding.
"""

import logging

from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.findings import KnowledgeFinding
from incidentflow.agent.tools.subagent_runtime import subagent_config

logger = logging.getLogger(__name__)


async def _consult_knowledge_agent(incident_context: str, config: RunnableConfig) -> str:
    """Run the Knowledge subagent and return its structured finding."""
    agent = build_knowledge_agent()
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=f"Incident context:\n{incident_context}")]},
        config=subagent_config(config),
    )
    finding = result.get("structured_response")
    if finding is None:
        return KnowledgeFinding(
            summary="The Knowledge agent stopped before writing its finding.",
            limitations=["The agent reached its call limit without a finding."],
            confidence=0,
        ).model_dump_json()
    return KnowledgeFinding.model_validate(finding).model_dump_json()


@tool(
    "ask_knowledge",
    description=(
        "Delegate to the Knowledge Agent, which searches read-only incident response guides, "
        "technical documentation, and confirmed incident lessons. Use for grounded procedures "
        "and similar documented incidents."
    ),
)
async def ask_knowledge(incident_context: str, config: RunnableConfig) -> str:
    """Delegate an incident question to the read-only Knowledge specialist."""
    try:
        return await _consult_knowledge_agent(incident_context, config)
    except Exception:
        logger.exception("Knowledge specialist delegation failed")
        return KnowledgeFinding(
            summary="Knowledge retrieval was unavailable during this investigation.",
            limitations=["No Pinecone evidence was collected because retrieval failed."],
            confidence=0,
        ).model_dump_json()

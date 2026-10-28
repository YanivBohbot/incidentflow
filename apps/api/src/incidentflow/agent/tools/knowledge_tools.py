"""Supervisor tool for knowledge-base retrieval."""

import logging

from langchain.tools import tool

from incidentflow.agent.agents_specialist.contracts import KnowledgeFinding
from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent

logger = logging.getLogger(__name__)


@tool(
    "ask_knowledge",
    description="Retrieve read-only incident response guides and technical documentation. Use for grounded procedures and similar documented incidents.",
)
def ask_knowledge(incident_context: str) -> str:
    """Delegate an incident question to the Knowledge specialist."""
    try:
        agent = build_knowledge_agent()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": incident_context}]},
            config={"recursion_limit": 6},
        )
        return result["structured_response"].model_dump_json()
    except Exception:
        logger.exception("Knowledge specialist delegation failed")
        return KnowledgeFinding(
            summary="Knowledge retrieval was unavailable during this investigation.",
            relevant_documents=[], evidence=[], recommended_steps=[],
            limitations=["No Pinecone evidence was collected because retrieval failed."],
            confidence=0,
        ).model_dump_json()

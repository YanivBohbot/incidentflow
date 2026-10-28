"""Compatibility exports for the specialist tools.

The implementations live in one module per integration so each tool can be
understood, tested, and evolved independently.
"""

from incidentflow.agent.tools.data_intelligence import ask_data_intelligence
from incidentflow.agent.tools.github import ask_github
from incidentflow.agent.tools.it_operations import ask_it_operations
from incidentflow.agent.tools.knowledge import ask_knowledge

__all__ = [
    "ask_data_intelligence",
    "ask_github",
    "ask_it_operations",
    "ask_knowledge",
]

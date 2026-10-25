from dataclasses import dataclass


@dataclass(frozen=True)
class AgentIdentity:
    technical_name: str
    display_name: str
    responsibility: str


INVESTIGATION_SUPERVISOR = AgentIdentity(
    technical_name="investigation_supervisor",
    display_name="Investigation Supervisor",
    responsibility="Coordinates specialists and consolidates their findings.",
)

IT_OPERATIONS_AGENT = AgentIdentity(
    technical_name="it_operations_agent",
    display_name="IT Operations Agent",
    responsibility="Investigates operational history and related incident tickets.",
)

DATA_INTELLIGENCE_AGENT = AgentIdentity(
    technical_name="data_intelligence_agent",
    display_name="Data Intelligence Agent",
    responsibility="Analyzes logs, events, and technical timelines.",
)

KNOWLEDGE_AGENT = AgentIdentity(
    technical_name="knowledge_agent",
    display_name="Knowledge Agent",
    responsibility="Retrieves incident response guides and technical documentation.",
)

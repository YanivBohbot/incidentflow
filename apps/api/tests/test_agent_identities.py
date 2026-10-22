from incidentflow.agent.identities import (
    DATA_INTELLIGENCE_AGENT,
    INVESTIGATION_SUPERVISOR,
    IT_OPERATIONS_AGENT,
    KNOWLEDGE_AGENT,
)


def test_agent_identities_have_unique_technical_names() -> None:
    identities = [
        INVESTIGATION_SUPERVISOR,
        IT_OPERATIONS_AGENT,
        DATA_INTELLIGENCE_AGENT,
        KNOWLEDGE_AGENT,
    ]

    assert len({identity.technical_name for identity in identities}) == len(identities)
    assert all(" " in identity.display_name for identity in identities)

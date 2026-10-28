from incidentflow.agent.evaluation.supervisor_routing import (
    SUPERVISOR_ROUTING_SCENARIOS,
    assess_delegations,
)


def test_routing_scenarios_cover_each_specialist_and_the_full_investigation() -> None:
    scenarios = {scenario.name: scenario for scenario in SUPERVISOR_ROUTING_SCENARIOS}

    assert scenarios["knowledge_only"].expected_tools == {"ask_knowledge"}
    assert scenarios["mongodb_only"].expected_tools == {"ask_data_intelligence"}
    assert scenarios["jira_only"].expected_tools == {"ask_it_operations"}
    assert scenarios["github_only"].expected_tools == {"ask_github"}
    assert scenarios["full_investigation"].expected_tools == {
        "ask_it_operations",
        "ask_data_intelligence",
        "ask_knowledge",
        "ask_github",
    }


def test_routing_assessment_rejects_extra_missing_and_excessive_delegations() -> None:
    assessment = assess_delegations(
        frozenset({"ask_knowledge"}),
        ("ask_knowledge", "ask_github", "ask_knowledge", "ask_knowledge"),
    )

    assert not assessment.passed
    assert assessment.unexpected_tools == {"ask_github"}
    assert assessment.missing_tools == set()
    assert assessment.excessively_repeated_tools == {"ask_knowledge"}


def test_routing_assessment_allows_one_evidence_driven_follow_up() -> None:
    assessment = assess_delegations(
        frozenset({"ask_knowledge"}),
        ("ask_knowledge", "ask_knowledge"),
    )

    assert assessment.passed

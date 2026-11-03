from incidentflow.agent.evaluation.investigation_reports import (
    EVALUATED_SPECIALISTS,
    INVESTIGATION_REPORT_SCENARIOS,
    consulted_required_specialists,
    evidence_is_attributed,
    scenario_reference,
    unavailable_sources_not_presented_as_live,
)

REFERENCE = {
    "required_specialists": ["ask_knowledge"],
    "expected_root_cause": "MongoDB connection pool exhaustion.",
    "unsafe_actions": [],
    "unavailable_sources": ["ask_data_intelligence"],
}


def test_scenarios_have_unique_names_and_known_specialists() -> None:
    names = [scenario.name for scenario in INVESTIGATION_REPORT_SCENARIOS]

    assert len(names) == len(set(names))
    for scenario in INVESTIGATION_REPORT_SCENARIOS:
        assert scenario.required_specialists <= set(EVALUATED_SPECIALISTS)
        assert scenario.expected_root_cause


def test_scenario_reference_is_json_safe() -> None:
    reference = scenario_reference(
        INVESTIGATION_REPORT_SCENARIOS[0], frozenset({"ask_github", "ask_data_intelligence"})
    )

    assert reference["required_specialists"] == ["ask_knowledge"]
    assert reference["unavailable_sources"] == ["ask_data_intelligence", "ask_github"]
    assert isinstance(reference["unsafe_actions"], list)


def test_consulted_required_specialists_reports_missing_specialists() -> None:
    passed = consulted_required_specialists(
        {"agents_consulted": ["ask_knowledge", "ask_github"]}, REFERENCE
    )
    failed = consulted_required_specialists({"agents_consulted": ["ask_github"]}, REFERENCE)

    assert passed["score"] == 1
    assert failed["score"] == 0
    assert "ask_knowledge" in failed["comment"]


def test_evidence_is_attributed_requires_sourced_evidence() -> None:
    assert evidence_is_attributed({"evidence": []})["score"] == 0
    assert evidence_is_attributed({"evidence": [{"source": " ", "detail": "x"}]})["score"] == 0
    assert evidence_is_attributed({"evidence": [{"source": "ask_knowledge"}]})["score"] == 1


def test_unavailable_sources_not_presented_as_live_rejects_fabricated_evidence() -> None:
    fabricated = {
        "evidence": [{"source": "ask_data_intelligence", "source_status": "live", "detail": "x"}]
    }
    honest = {
        "evidence": [
            {"source": "ask_data_intelligence", "source_status": "unavailable", "detail": "x"},
            {"source": "ask_knowledge", "source_status": "live", "detail": "y"},
        ]
    }

    assert unavailable_sources_not_presented_as_live(fabricated, REFERENCE)["score"] == 0
    assert unavailable_sources_not_presented_as_live(honest, REFERENCE)["score"] == 1

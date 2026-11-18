import json

from evaluation.harness.fixtures import FINDING_MODELS
from evaluation.scenarios.catalog import (
    REPORT_SCENARIOS,
    TRAJECTORY_SCENARIOS,
    EvaluationScenario,
    report_example,
    trajectory_example,
)
from evaluation.scenarios.supervisor_routing import SUPERVISOR_ROUTING_SCENARIOS

ALL_TOOLS = frozenset(FINDING_MODELS)
ALL_SCENARIOS = (*TRAJECTORY_SCENARIOS, *REPORT_SCENARIOS)


def _evidence_sources(finding_json: str) -> set[str]:
    return {item["source"] for item in json.loads(finding_json).get("evidence", [])}


def test_frozen_findings_validate_against_their_finding_models() -> None:
    for scenario in ALL_SCENARIOS:
        for tool, raw in scenario.frozen_findings.items():
            FINDING_MODELS[tool].model_validate_json(raw)


def test_frozen_findings_support_required_specialists_with_confidence() -> None:
    for scenario in ALL_SCENARIOS:
        assert scenario.required_specialists <= set(scenario.frozen_findings), scenario.name
        for tool in scenario.required_specialists:
            assert json.loads(scenario.frozen_findings[tool])["confidence"] > 0, scenario.name


def test_scenario_names_are_unique_within_each_dataset() -> None:
    for group in (TRAJECTORY_SCENARIOS, REPORT_SCENARIOS):
        names = [scenario.name for scenario in group]
        assert len(names) == len(set(names))


def test_catalog_sizes_and_required_trajectory_scenarios() -> None:
    names = {scenario.name for scenario in TRAJECTORY_SCENARIOS}
    assert len(TRAJECTORY_SCENARIOS) >= 8
    assert len(REPORT_SCENARIOS) >= 8
    assert {"cloudwatch_and_github_deploy_regression", "no_specialist_needed_greeting"} <= names
    greeting = next(s for s in TRAJECTORY_SCENARIOS if s.name == "no_specialist_needed_greeting")
    assert greeting.required_specialists == frozenset()
    assert greeting.forbidden_specialists == ALL_TOOLS


def test_report_scenarios_keep_the_three_existing_names() -> None:
    names = {scenario.name for scenario in REPORT_SCENARIOS}
    assert {"EVAL-PAY-001", "EVAL-AUTH-002", "EVAL-CODE-003"} <= names


def test_key_facts_appear_in_request_and_in_frozen_findings() -> None:
    for scenario in ALL_SCENARIOS:
        corpus = " ".join(scenario.frozen_findings.values())
        for fact in scenario.key_facts:
            assert fact in scenario.incident_request, (scenario.name, fact)
            if scenario.frozen_findings:
                assert fact in corpus, (scenario.name, fact)


def test_report_scenarios_have_root_cause_and_cite_correlation_ids() -> None:
    for scenario in REPORT_SCENARIOS:
        assert scenario.expected_root_cause, scenario.name
        assert scenario.unsafe_actions, scenario.name
        assert any(fact.startswith("incidentflow-") for fact in scenario.key_facts), scenario.name


def test_there_is_an_insufficient_evidence_report_scenario() -> None:
    assert any(
        "cannot be determined" in (scenario.expected_root_cause or "")
        for scenario in REPORT_SCENARIOS
    )


def test_trajectory_forbidden_specialists_are_disjoint_and_excluded_in_the_request() -> None:
    for scenario in TRAJECTORY_SCENARIOS:
        assert not scenario.required_specialists & scenario.forbidden_specialists
        if scenario.forbidden_specialists and scenario.required_specialists:
            assert "Do not inspect" in scenario.incident_request, scenario.name


def test_trajectory_example_shape() -> None:
    scenario = TRAJECTORY_SCENARIOS[0]

    example = trajectory_example(scenario)

    assert example["inputs"] == {
        "incident_request": scenario.incident_request,
        "scenario": scenario.name,
    }
    assert example["metadata"] == {"scenario": scenario.name}
    assert set(example["outputs"]) == {"required_specialists", "forbidden_specialists", "key_facts"}
    for key in example["outputs"]:
        assert example["outputs"][key] == sorted(example["outputs"][key])


def test_report_example_shape_and_unavailable_sources() -> None:
    for scenario in REPORT_SCENARIOS:
        example = report_example(scenario)
        outputs = example["outputs"]

        assert example["metadata"] == {"scenario": scenario.name}
        assert set(outputs) == {
            "required_specialists",
            "expected_root_cause",
            "unsafe_actions",
            "unavailable_sources",
            "source_tools",
            "frozen_findings",
            "key_facts",
        }
        assert outputs["unavailable_sources"] == sorted(ALL_TOOLS - set(scenario.frozen_findings))
        assert outputs["frozen_findings"] == dict(scenario.frozen_findings)
        for key in ("required_specialists", "unsafe_actions", "unavailable_sources", "key_facts"):
            assert outputs[key] == sorted(outputs[key])


def test_source_tools_map_evidence_sources_tools_and_aliases() -> None:
    for scenario in REPORT_SCENARIOS:
        for tool, raw in scenario.frozen_findings.items():
            assert scenario.source_tools[tool] == tool
            for source in _evidence_sources(raw):
                assert scenario.source_tools[source] == tool, (scenario.name, source)
        assert set(scenario.source_tools.values()) <= set(scenario.frozen_findings)


def test_routing_scenarios_are_derived_from_the_trajectory_catalog() -> None:
    by_name = {s.name: s for s in TRAJECTORY_SCENARIOS}

    assert len(SUPERVISOR_ROUTING_SCENARIOS) == 6
    for routing in SUPERVISOR_ROUTING_SCENARIOS:
        source: EvaluationScenario = by_name[routing.name]
        assert routing.request == source.incident_request
        assert routing.expected_tools == source.required_specialists

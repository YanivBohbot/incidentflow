import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.evaluators import code

TRAJECTORY_FUNCS = [getattr(code, name) for name in code.TRAJECTORY_CODE_EVALUATORS]
REPORT_EVALUATOR_FUNCS = [getattr(code, name) for name in code.REPORT_CODE_EVALUATORS]
ALL_CODE_EVALUATORS = TRAJECTORY_FUNCS + REPORT_EVALUATOR_FUNCS

FULL_REFERENCE = {
    "required_specialists": ["ask_it_operations", "ask_github"],
    "forbidden_specialists": ["ask_cloudwatch"],
    "key_facts": ["INC-42", "checkout"],
    "expected_root_cause": "bad deploy",
    "unsafe_actions": [],
    "unavailable_sources": ["ask_cloudwatch"],
    "source_tools": {"Jira": "ask_it_operations", "GitHub": "ask_github", "Logs": "ask_cloudwatch"},
    "frozen_findings": {},
}

GOOD_OUTPUTS = {
    "report": {
        "summary": "Bad deploy broke checkout",
        "agents_consulted": ["ask_it_operations", "ask_github"],
        "evidence": [
            {"source": "Jira", "detail": "INC-42 opened", "source_status": "live"},
            {"source": "GitHub", "detail": "commit abc", "source_status": "simulated"},
            {"source": "Logs", "detail": "", "source_status": "unavailable"},
        ],
        "confidence": 0.8,
    },
    "delegations": [
        {"tool": "ask_it_operations", "args": {"incident_context": "Incident INC-42 on Checkout"}},
        {"tool": "ask_github", "args": {"incident_context": "recent commits"}},
    ],
    "graph_path": ["validate", "prepare", "investigate", "capture_report", "finalize"],
    "interrupts": [],
    "lifecycle": "completed",
    "errors": [],
}


def _wrap(outputs, as_namespace):
    return SimpleNamespace(outputs=outputs) if as_namespace else {"outputs": outputs}


def _call(evaluator, outputs, reference=None, as_namespace=False):
    ref = FULL_REFERENCE if reference is None else reference
    return evaluator(_wrap(outputs, as_namespace), _wrap(ref, as_namespace))


def _variant(**changes):
    return {**GOOD_OUTPUTS, **changes}


def _report(**changes):
    return {**GOOD_OUTPUTS["report"], **changes}


# (evaluator name, failing outputs, failing reference override)
FAIL_CASES = [
    (
        "required_specialists_called",
        _variant(delegations=[GOOD_OUTPUTS["delegations"][0]]),
        {},
    ),
    (
        "forbidden_specialists_not_called",
        _variant(
            delegations=[*GOOD_OUTPUTS["delegations"], {"tool": "ask_cloudwatch", "args": {}}]
        ),
        {},
    ),
    (
        "delegation_calls_within_limit",
        _variant(delegations=[GOOD_OUTPUTS["delegations"][0]] * 3),
        {},
    ),
    (
        "delegation_args_contain_key_facts",
        _variant(delegations=[{"tool": "ask_github", "args": {"incident_context": "INC-42"}}]),
        {},
    ),
    ("graph_path_valid", _variant(graph_path=["validate", "prepare", "investigate", "fail"]), {}),
    ("report_has_required_fields", _variant(report=_report(confidence=1.5)), {}),
    (
        "evidence_attributed",
        _variant(report=_report(evidence=[{"source": "", "detail": "x", "source_status": "live"}])),
        {},
    ),
    (
        "evidence_from_delegated_sources",
        _variant(
            report=_report(evidence=[{"source": "Metrics", "detail": "x", "source_status": "live"}])
        ),
        {},
    ),
    (
        "no_live_evidence_from_unavailable",
        _variant(
            report=_report(evidence=[{"source": "Logs", "detail": "x", "source_status": "live"}])
        ),
        {},
    ),
    (
        "evidence_status_matches_findings",
        _variant(
            report=_report(evidence=[{"source": "GitHub", "detail": "x", "source_status": "live"}])
        ),
        {
            "frozen_findings": {
                "ask_github": '{"evidence": [{"source": "GitHub", "source_status": "simulated"}]}'
            }
        },
    ),
]


@pytest.mark.parametrize("as_namespace", [False, True])
@pytest.mark.parametrize("evaluator", ALL_CODE_EVALUATORS)
def test_code_evaluator_passes_on_good_run(evaluator, as_namespace) -> None:
    result = _call(evaluator, GOOD_OUTPUTS, as_namespace=as_namespace)
    assert result["score"] == 1, result
    assert isinstance(result["comment"], str)
    assert set(result) == {"score", "comment"}


@pytest.mark.parametrize("as_namespace", [False, True])
@pytest.mark.parametrize(("name", "outputs", "ref"), FAIL_CASES, ids=[c[0] for c in FAIL_CASES])
def test_code_evaluator_fails_on_bad_run(name, outputs, ref, as_namespace) -> None:
    result = _call(getattr(code, name), outputs, {**FULL_REFERENCE, **ref}, as_namespace)
    assert result["score"] < 1, result
    assert result["comment"]


def test_every_evaluator_has_a_fail_case() -> None:
    assert {c[0] for c in FAIL_CASES} == {fn.__name__ for fn in ALL_CODE_EVALUATORS}


@pytest.mark.parametrize("evaluator", ALL_CODE_EVALUATORS)
def test_code_evaluator_scores_zero_when_run_has_no_outputs(evaluator) -> None:
    result = evaluator({"outputs": None}, {"outputs": FULL_REFERENCE})
    assert result["score"] == 0 and result["comment"]
    assert "no outputs" in result["comment"]


@pytest.mark.parametrize("evaluator", REPORT_EVALUATOR_FUNCS)
def test_report_evaluator_scores_zero_when_report_is_missing(evaluator) -> None:
    run = {"outputs": {"report": None, "lifecycle": "failed", "graph_path": ["validate", "fail"]}}
    assert evaluator(run, {"outputs": FULL_REFERENCE})["score"] == 0


def test_required_specialists_empty_list_scores_one() -> None:
    ref = {**FULL_REFERENCE, "required_specialists": []}
    assert (
        code.required_specialists_called(_wrap(GOOD_OUTPUTS, False), _wrap(ref, False))["score"]
        == 1
    )


def test_key_facts_score_is_fraction_found_case_insensitive() -> None:
    outputs = _variant(delegations=[{"tool": "ask_github", "args": {"incident_context": "inc-42"}}])
    result = _call(code.delegation_args_contain_key_facts, outputs)
    assert result["score"] == 0.5
    assert "checkout" in result["comment"]


def test_key_facts_empty_scores_one_and_no_delegations_scores_zero() -> None:
    ref = {**FULL_REFERENCE, "key_facts": []}
    empty = _call(code.delegation_args_contain_key_facts, _variant(delegations=[]), ref)
    assert empty == {"score": 1, "comment": "no key facts"}
    none = _call(code.delegation_args_contain_key_facts, _variant(delegations=[]))
    assert none["score"] == 0


def test_graph_path_valid_accepts_review_with_report_review_interrupt() -> None:
    path = ["validate", "prepare", "investigate", "capture_report", "review"]
    ok = _variant(graph_path=path, interrupts=[{"kind": "report_review", "tool": None}])
    assert _call(code.graph_path_valid, ok)["score"] == 1
    assert _call(code.graph_path_valid, _variant(graph_path=path))["score"] == 0


def test_unavailable_evidence_items_are_ignored_for_delegated_sources() -> None:
    outputs = _variant(
        report=_report(
            evidence=[{"source": "Unknown", "detail": "", "source_status": "unavailable"}]
        )
    )
    assert _call(code.evidence_from_delegated_sources, outputs)["score"] == 1


def test_code_evaluators_import_only_the_standard_library() -> None:
    tree = ast.parse(Path(code.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert roots <= set(__import__("sys").stdlib_module_names)


def test_evaluator_name_tuples_match_defined_functions() -> None:
    assert len(code.TRAJECTORY_CODE_EVALUATORS) == 4
    assert len(code.REPORT_CODE_EVALUATORS) == 6
    assert all(isinstance(n, str) for n in ALL_CODE_NAMES)


ALL_CODE_NAMES = (*code.TRAJECTORY_CODE_EVALUATORS, *code.REPORT_CODE_EVALUATORS)


@pytest.mark.parametrize("name", ALL_CODE_NAMES)
def test_each_evaluator_runs_standalone_from_its_source(name) -> None:
    source = inspect.getsource(getattr(code, name))
    namespace: dict = {}
    exec(source, namespace)  # noqa: S102 - mirrors the LangSmith upload sandbox
    result = namespace[name](_wrap(GOOD_OUTPUTS, False), _wrap(FULL_REFERENCE, False))
    assert result["score"] == 1, result


def _evidence(*items):
    return _variant(report=_report(evidence=[dict(item) for item in items]))


def test_delegated_sources_match_a_known_alias_inside_a_descriptive_source_name() -> None:
    outputs = _evidence(
        {"source": "Jira incident tickets", "detail": "INC-42", "source_status": "simulated"},
        {"source": "github commits", "detail": "abc", "source_status": "simulated"},
    )
    assert _call(code.evidence_from_delegated_sources, outputs)["score"] == 1


def test_delegated_sources_still_fail_for_a_named_specialist_that_was_not_called() -> None:
    outputs = _evidence(
        {"source": "Logs from CloudWatch", "detail": "x", "source_status": "simulated"},
    )
    reference = {**FULL_REFERENCE, "source_tools": {**FULL_REFERENCE["source_tools"]}}
    result = _call(code.evidence_from_delegated_sources, outputs, reference)
    assert result["score"] == 0
    assert "undelegated" in result["comment"]


def test_delegated_sources_still_fail_for_an_unknown_source() -> None:
    outputs = _evidence({"source": "Slack", "detail": "x", "source_status": "simulated"})
    result = _call(code.evidence_from_delegated_sources, outputs)
    assert result["score"] == 0
    assert "Slack" in result["comment"]


def test_live_evidence_check_matches_aliases_inside_descriptive_source_names() -> None:
    outputs = _evidence({"source": "Logs from CloudWatch", "detail": "x", "source_status": "live"})
    assert _call(code.no_live_evidence_from_unavailable, outputs)["score"] == 0


def test_source_aliases_include_specialist_agent_names() -> None:
    from evaluation.scenarios.scenario_model import SOURCE_ALIASES

    assert "Data Intelligence" in SOURCE_ALIASES["ask_data_intelligence"]
    assert "IT Operations" in SOURCE_ALIASES["ask_it_operations"]


def _status_reference(*statuses: str) -> dict:
    finding = {
        "evidence": [{"source": "GitHub", "detail": "d", "source_status": s} for s in statuses]
    }
    import json as _json

    return {**FULL_REFERENCE, "frozen_findings": {"ask_github": _json.dumps(finding)}}


def test_status_check_fails_when_simulated_finding_evidence_is_reported_live() -> None:
    outputs = _evidence({"source": "GitHub commits", "detail": "abc", "source_status": "live"})
    result = _call(code.evidence_status_matches_findings, outputs, _status_reference("simulated"))
    assert result["score"] == 0
    assert "GitHub commits" in result["comment"]


def test_status_check_passes_when_report_copies_the_finding_status() -> None:
    outputs = _evidence({"source": "GitHub", "detail": "abc", "source_status": "simulated"})
    result = _call(code.evidence_status_matches_findings, outputs, _status_reference("simulated"))
    assert result["score"] == 1


def test_status_check_accepts_live_when_the_finding_was_live() -> None:
    outputs = _evidence({"source": "GitHub", "detail": "abc", "source_status": "live"})
    result = _call(code.evidence_status_matches_findings, outputs, _status_reference("live"))
    assert result["score"] == 1


def test_status_check_ignores_sources_without_a_frozen_finding() -> None:
    outputs = _evidence({"source": "Jira", "detail": "x", "source_status": "live"})
    result = _call(code.evidence_status_matches_findings, outputs, _status_reference("simulated"))
    assert result["score"] == 1

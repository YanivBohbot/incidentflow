from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from evaluation import upload_evaluators
from evaluation.evaluators.code import REPORT_CODE_EVALUATORS, TRAJECTORY_CODE_EVALUATORS
from evaluation.harness.report_table import (
    ExperimentScores,
    fetch_experiment_scores,
    render_summary,
)
from evaluation.harness.runner import DATASETS


def _scores(dataset: str, name: str, scores: dict[str, float]) -> ExperimentScores:
    return ExperimentScores(dataset=dataset, name=name, url=f"https://x/{name}", scores=scores)


def test_render_summary_shows_delta_against_previous() -> None:
    dataset = DATASETS["trajectory"]
    latest = [_scores(dataset, "exp-2", {"routing": 1.0})]
    previous = {dataset: _scores(dataset, "exp-1", {"routing": 0.67})}
    text = render_summary(latest, previous)
    assert "| routing | 1.00 | 0.67 | +0.33 |" in text
    assert "https://x/exp-2" in text
    assert "How to run" in text
    assert "python -m evaluation.upload_evaluators" in text


def test_render_summary_marks_missing_previous_as_dash() -> None:
    dataset = DATASETS["reports"]
    text = render_summary([_scores(dataset, "exp-1", {"b": 0.5, "a": 1.0})], {})
    assert "| a | 1.00 | — | — |" in text
    assert text.index("| a |") < text.index("| b |")
    assert "No experiments yet." in text  # the trajectory dataset has none


def test_render_summary_formats_negative_and_zero_delta() -> None:
    dataset = DATASETS["reports"]
    latest = [_scores(dataset, "n", {"a": 0.5, "b": 1.0})]
    previous = {dataset: _scores(dataset, "o", {"a": 0.6, "b": 1.0})}
    text = render_summary(latest, previous)
    assert "-0.10" in text
    assert "+0.00" in text


def test_upload_dry_run_lists_every_evaluator_once(capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_secret_key")
    assert upload_evaluators.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    total = len(TRAJECTORY_CODE_EVALUATORS) + len(REPORT_CODE_EVALUATORS)
    assert out.count("evaluator upload") == total
    assert "--yes" not in out
    assert "lsv2_secret_key" not in out


def test_upload_commands_never_contain_yes_or_api_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_secret_key")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def runner(cmd: list[str], env: dict[str, str]) -> int:
        calls.append((cmd, env))
        return 0

    assert upload_evaluators.main([], runner=runner) == 0
    assert len(calls) == len(TRAJECTORY_CODE_EVALUATORS) + len(REPORT_CODE_EVALUATORS)
    for cmd, env in calls:
        assert "--yes" not in cmd
        assert not any("lsv2_secret_key" in part for part in cmd)
        assert env["LANGSMITH_API_KEY"] == "lsv2_secret_key"


def test_fetch_experiment_scores_picks_latest_two_and_averages() -> None:
    def project(name: str, day: int, avg: float) -> SimpleNamespace:
        return SimpleNamespace(
            name=name,
            start_time=datetime(2026, 11, day),
            url=f"https://ls/{name}",
            feedback_stats={"routing": {"n": 3, "avg": avg}},
            extra={},
        )

    class FakeClient:
        def list_projects(self, **kwargs: Any) -> list[SimpleNamespace]:
            assert kwargs["reference_dataset_name"] == "ds"
            return [project("mid", 2, 0.5), project("old", 1, 0.1), project("new", 3, 0.9)]

    latest, previous = fetch_experiment_scores(FakeClient(), "ds")
    assert latest is not None and previous is not None
    assert (latest.name, previous.name) == ("new", "mid")
    assert latest.scores == {"routing": 0.9}
    assert latest.url == "https://ls/new"


def test_fetch_experiment_scores_returns_none_without_experiments() -> None:
    class Empty:
        def list_projects(self, **kwargs: Any) -> list[Any]:
            return []

    assert fetch_experiment_scores(Empty(), "ds") == (None, None)


def _fake(name: str, start: datetime | None, avg: float) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        start_time=start,
        url="",
        feedback_stats={"m": {"avg": avg}},
        extra={},
    )


def test_fetch_experiment_scores_tolerates_missing_and_naive_start_times() -> None:
    projects = [
        _fake("never", None, 0.1),
        _fake("naive", datetime(2026, 11, 2), 0.5),
        _fake("aware", datetime(2026, 11, 3, tzinfo=UTC), 0.9),
    ]

    class FakeClient:
        def list_projects(self, **kwargs: Any) -> list[SimpleNamespace]:
            return projects

    latest, previous = fetch_experiment_scores(FakeClient(), "ds")
    assert latest is not None and previous is not None
    assert (latest.name, previous.name) == ("aware", "naive")


def test_fetch_experiment_scores_single_experiment_has_no_previous() -> None:
    class FakeClient:
        def list_projects(self, **kwargs: Any) -> list[SimpleNamespace]:
            return [_fake("only", datetime(2026, 11, 1), 0.7)]

    latest, previous = fetch_experiment_scores(FakeClient(), "ds")
    assert latest is not None and latest.scores == {"m": 0.7}
    assert previous is None


def test_missing_cli_reports_clear_error(capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("LANGSMITH_CLI", "Z:/definitely/missing/langsmith.exe")
    assert upload_evaluators.main([]) == 1
    assert "set LANGSMITH_CLI" in capsys.readouterr().out

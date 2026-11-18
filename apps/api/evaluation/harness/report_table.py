"""Fetch the latest LangSmith experiment scores and render them as a Markdown summary."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from evaluation.harness.runner import DATASETS


@dataclass
class ExperimentScores:
    dataset: str
    name: str
    url: str
    scores: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)


def _project_scores(dataset: str, project: Any) -> ExperimentScores:
    stats = project.feedback_stats or {}
    scores = {
        key: float(value["avg"])
        for key, value in stats.items()
        if isinstance(value, dict) and value.get("avg") is not None
    }
    url = getattr(project, "url", None) or ""
    metadata = (getattr(project, "extra", None) or {}).get("metadata") or {}
    return ExperimentScores(dataset, project.name, url, scores, dict(metadata))


def _sort_time(value: datetime | None) -> datetime:
    """Sort key tolerant of missing and naive start times (naive is treated as UTC)."""
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def fetch_experiment_scores(
    client: Any, dataset: str
) -> tuple[ExperimentScores | None, ExperimentScores | None]:
    """Return (latest, previous) experiments for a dataset by start time, with mean scores."""
    projects = list(
        client.list_projects(reference_dataset_name=dataset, include_stats=True, limit=50)
    )
    projects.sort(key=lambda project: _sort_time(project.start_time), reverse=True)
    converted = [_project_scores(dataset, project) for project in projects[:2]]
    converted += [None] * (2 - len(converted))
    return converted[0], converted[1]


def _delta(latest: float, previous: float | None) -> str:
    return "—" if previous is None else f"{latest - previous:+.2f}"


def _section(
    dataset: str, latest: ExperimentScores | None, previous: ExperimentScores | None
) -> list[str]:
    lines = [f"## {dataset}", ""]
    if latest is None:
        return [*lines, "No experiments yet.", ""]
    link = f"[{latest.name}]({latest.url})" if latest.url else latest.name
    lines.append(f"Latest experiment: {link}")
    if previous is not None:
        prev_link = f"[{previous.name}]({previous.url})" if previous.url else previous.name
        lines.append(f"Previous experiment: {prev_link}")
    meta = [
        f"{key}: {latest.metadata[key]}"
        for key in ("model", "judge_model", "prompt_hash")
        if latest.metadata.get(key)
    ]
    if meta:
        lines.append(f"Run settings: {', '.join(meta)}")
    lines += ["", "| Metric | Latest | Previous | Δ |", "| --- | --- | --- | --- |"]
    for metric in sorted(latest.scores):
        value = latest.scores[metric]
        before = previous.scores.get(metric) if previous else None
        shown = "—" if before is None else f"{before:.2f}"
        lines.append(f"| {metric} | {value:.2f} | {shown} | {_delta(value, before)} |")
    return [*lines, ""]


def render_summary(latest: list[ExperimentScores], previous: dict[str, ExperimentScores]) -> str:
    """Render one table per dataset (Metric | Latest | Previous | Δ) plus run instructions."""
    by_dataset = {item.dataset: item for item in latest}
    lines = ["# Evaluation summary", ""]
    for dataset in DATASETS.values():
        lines += _section(dataset, by_dataset.get(dataset), previous.get(dataset))
    lines += [
        "## How to run",
        "",
        "From `apps/api`:",
        "",
        "```powershell",
        'pip install -e ".[dev,eval]"',
        "python -m evaluation.run --suite all",
        "python -m evaluation.upload_evaluators",
        "python -m evaluation.summary",
        "```",
        "",
    ]
    return "\n".join(lines)

"""Write docs/evaluation.md from the latest LangSmith experiments.

Run from ``apps/api``: ``python -m evaluation.summary``.
"""

from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

from evaluation.harness.report_table import (
    ExperimentScores,
    fetch_experiment_scores,
    render_summary,
)
from evaluation.harness.runner import DATASETS

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = REPO_ROOT / "docs" / "evaluation.md"


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    client = Client()
    latest: list[ExperimentScores] = []
    previous: dict[str, ExperimentScores] = {}
    for dataset in DATASETS.values():
        newest, older = fetch_experiment_scores(client, dataset)
        if newest is not None:
            latest.append(newest)
        if older is not None:
            previous[dataset] = older
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_summary(latest, previous), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

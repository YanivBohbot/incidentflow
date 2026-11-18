"""Testable core of the evaluation entry point: run functions and experiment orchestration."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

import langsmith
from langgraph.checkpoint.memory import InMemorySaver

from evaluation.evaluators.judges import build_judge_model, build_judges, prompt_hash
from evaluation.harness.dataset_sync import sync_dataset
from evaluation.harness.fixtures import CallLog, fixture_delegations
from evaluation.harness.trajectory import run_workflow_recorded
from evaluation.scenarios.catalog import (
    REPORT_SCENARIOS,
    TRAJECTORY_SCENARIOS,
    report_example,
    trajectory_example,
)
from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.core.config import get_settings

Suite = Literal["trajectory", "reports"]

DATASETS: dict[str, str] = {
    "trajectory": "incidentflow-supervisor-trajectory",
    "reports": "incidentflow-investigation-reports",
}
DESCRIPTIONS: dict[str, str] = {
    "trajectory": "Incident requests replayed to check which specialists the supervisor consults.",
    "reports": "Incident requests with frozen specialist findings and known root causes.",
}
_SCENARIOS = {"trajectory": TRAJECTORY_SCENARIOS, "reports": REPORT_SCENARIOS}
_EXAMPLE_BUILDERS = {"trajectory": trajectory_example, "reports": report_example}
_JUDGE_NAMES = {
    "trajectory": ["investigation_path_reasonable"],
    "reports": ["root_cause_identified", "report_grounded_in_findings", "safe_remediation"],
}


def _default_workflow_factory(supervisor: Any) -> Any:
    return build_investigation_workflow(supervisor, checkpointer=InMemorySaver())


def make_run_function(
    suite: Suite,
    *,
    live: bool,
    supervisor_factory: Callable[..., Any] = build_investigation_supervisor,
    workflow_factory: Callable[[Any], Any] = _default_workflow_factory,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Build the function LangSmith calls per example; every call gets its own log and workflow.

    In live mode the real delegation tools do not write to the call log, so the recorder's
    top-level delegation calls fill ``delegations`` instead.
    """
    scenarios = {scenario.name: scenario for scenario in _SCENARIOS[suite]}

    async def run(inputs: dict[str, Any]) -> dict[str, Any]:
        name = inputs["scenario"]
        if name not in scenarios:
            raise KeyError(f"Unknown {suite} scenario {name!r}; known: {sorted(scenarios)}")
        call_log: CallLog = []
        tools = None if live else fixture_delegations(scenarios[name].frozen_findings, call_log)
        workflow = workflow_factory(supervisor_factory(tools=tools))
        return await run_workflow_recorded(workflow, inputs["incident_request"], call_log)

    return run


def _print_scores(totals: dict[str, list[float]], errors: dict[str, int]) -> None:
    print("
Average scores:")
    for key in sorted(totals.keys() | errors.keys()):
        values = totals.get(key, [])
        mean = f"{sum(values) / len(values):.2f}" if values else "n/a"
        suffix = f" ({errors[key]} errored)" if errors.get(key) else ""
        print(f"  {key}: {mean}{suffix}")


async def run_suite(
    suite: Suite,
    *,
    live: bool,
    repetitions: int,
    max_concurrency: int,
    client: Any,
    aevaluate_fn: Callable[..., Awaitable[Any]] = langsmith.aevaluate,
    judge_model: Any = None,
) -> str:
    """Sync the suite's dataset, run the experiment with LLM judges, and return its name."""
    settings = get_settings()
    dataset = DATASETS[suite]
    examples = [_EXAMPLE_BUILDERS[suite](scenario) for scenario in _SCENARIOS[suite]]
    print(f"{dataset}: {sync_dataset(client, dataset, DESCRIPTIONS[suite], examples)}")

    judges = {fn.__name__: fn for fn in build_judges(judge_model or build_judge_model(settings))}
    results = await aevaluate_fn(
        make_run_function(suite, live=live),
        data=dataset,
        evaluators=[judges[name] for name in _JUDGE_NAMES[suite]],
        experiment_prefix=suite,
        num_repetitions=repetitions,
        max_concurrency=max_concurrency,
        metadata={
            "model": settings.openai_model,
            "judge_model": settings.eval_judge_model,
            "prompt_hash": prompt_hash(),
            "live_integrations": live,
            "suite": suite,
        },
        client=client,
    )
    totals: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    async for row in results:
        scenario = row["example"].metadata.get("scenario")
        scores = {r.key: r.score for r in row["evaluation_results"]["results"]}
        print(f"{scenario}: {scores}")
        for key, value in scores.items():
            if value is None:
                errors[key] = errors.get(key, 0) + 1
            else:
                totals.setdefault(key, []).append(value)
    _print_scores(totals, errors)
    print(f"\nExperiment: {results.experiment_name}")
    return results.experiment_name

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.harness import runner
from evaluation.scenarios.catalog import REPORT_SCENARIOS, TRAJECTORY_SCENARIOS
from incidentflow.core.config import get_settings


class FakeWorkflow:
    """Calls its stub delegation tool once, so the call log records the scenario's own run."""

    def __init__(self, tools: list[Any]) -> None:
        self.tools = {tool.name: tool for tool in tools}

    async def astream(self, state: dict[str, Any], config: Any, stream_mode: str):
        await asyncio.sleep(0)
        await self.tools["ask_github"].ainvoke({"incident_context": state["incident_request"]})
        await asyncio.sleep(0)
        yield {"investigate": {}}

    async def aget_state(self, config: Any) -> Any:
        return SimpleNamespace(values={"report": None, "investigation_lifecycle": "COMPLETED"})


def make_fakes(seen: list[Any]):
    def supervisor_factory(tools: Any = None) -> Any:
        seen.append(tools)
        return tools

    def workflow_factory(supervisor: Any) -> FakeWorkflow:
        return FakeWorkflow(supervisor)

    return supervisor_factory, workflow_factory


@pytest.mark.anyio
async def test_run_function_isolates_call_logs_between_concurrent_runs() -> None:
    seen: list[Any] = []
    supervisor_factory, workflow_factory = make_fakes(seen)
    run = runner.make_run_function(
        "trajectory",
        live=False,
        supervisor_factory=supervisor_factory,
        workflow_factory=workflow_factory,
    )
    first, second = TRAJECTORY_SCENARIOS[0], TRAJECTORY_SCENARIOS[1]
    out_a, out_b = await asyncio.gather(
        run({"scenario": first.name, "incident_request": "request A"}),
        run({"scenario": second.name, "incident_request": "request B"}),
    )
    assert [d["args"] for d in out_a["delegations"]] == [{"incident_context": "request A"}]
    assert [d["args"] for d in out_b["delegations"]] == [{"incident_context": "request B"}]
    assert len(seen) == 2 and all(tools for tools in seen)


@pytest.mark.anyio
async def test_run_function_live_uses_real_tools() -> None:
    seen: list[Any] = []
    supervisor_factory, _ = make_fakes(seen)

    class Idle(FakeWorkflow):
        async def astream(self, state, config, stream_mode):
            yield {"investigate": {}}

    run = runner.make_run_function(
        "reports",
        live=True,
        supervisor_factory=supervisor_factory,
        workflow_factory=lambda supervisor: Idle([]),
    )
    out = await run({"scenario": REPORT_SCENARIOS[0].name, "incident_request": "x"})
    assert seen == [None] and out["delegations"] == []


@pytest.mark.anyio
async def test_run_function_rejects_unknown_scenario() -> None:
    run = runner.make_run_function("reports", live=False)
    with pytest.raises(KeyError, match="no-such"):
        await run({"scenario": "no-such", "incident_request": "x"})


class FakeClient:
    def has_dataset(self, **_: Any) -> bool:
        return True

    def list_examples(self, **_: Any) -> list[Any]:
        return []

    def create_examples(self, **_: Any) -> None:
        pass

    def update_dataset_tag(self, **_: Any) -> None:
        pass


class FakeResults:
    experiment_name = "reports-abc"

    def __aiter__(self):
        async def rows():
            yield {
                "example": SimpleNamespace(metadata={"scenario": "s"}),
                "evaluation_results": {
                    "results": [SimpleNamespace(key="safe_remediation", score=1)]
                },
            }

        return rows()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("suite", "judge_names"),
    [
        ("trajectory", ["investigation_path_reasonable"]),
        (
            "reports",
            ["root_cause_identified", "report_grounded_in_findings", "safe_remediation"],
        ),
    ],
)
async def test_run_suite_passes_only_judges_and_repetitions(suite, judge_names, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    get_settings.cache_clear()
    captured: dict[str, Any] = {}

    async def fake_aevaluate(run_fn: Any, **kwargs: Any) -> FakeResults:
        captured.update(kwargs, run_fn=run_fn)
        return FakeResults()

    client = FakeClient()
    name = await runner.run_suite(
        suite,
        live=False,
        repetitions=3,
        max_concurrency=2,
        client=client,
        aevaluate_fn=fake_aevaluate,
        judge_model=SimpleNamespace(with_structured_output=lambda *a, **k: None),
    )
    assert name == "reports-abc"
    assert captured["num_repetitions"] == 3
    assert captured["max_concurrency"] == 2
    assert captured["data"] == runner.DATASETS[suite]
    assert captured["experiment_prefix"] == suite
    assert captured["client"] is client
    assert [fn.__name__ for fn in captured["evaluators"]] == judge_names
    settings = get_settings()
    assert captured["metadata"] == {
        "model": settings.openai_model,
        "judge_model": settings.eval_judge_model,
        "prompt_hash": captured["metadata"]["prompt_hash"],
        "live_integrations": False,
        "suite": suite,
    }
    assert callable(captured["run_fn"])
    get_settings.cache_clear()

import json
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.evaluators import judges
from incidentflow.core.config import Settings, get_settings


class FakeStructured:
    def __init__(self, grade: dict[str, Any], prompts: list[Any]) -> None:
        self.grade = grade
        self.prompts = prompts

    async def ainvoke(self, prompt: Any) -> dict[str, Any]:
        self.prompts.append(prompt)
        return self.grade


class FakeModel:
    def __init__(self, grade: dict[str, Any]) -> None:
        self.grade = grade
        self.prompts: list[Any] = []
        self.structured_kwargs: dict[str, Any] = {}

    def with_structured_output(self, schema: Any, **kwargs: Any) -> FakeStructured:
        self.structured_kwargs = kwargs
        return FakeStructured(self.grade, self.prompts)


REPORT = {
    "summary": "Bad deploy broke checkout",
    "evidence": [{"source": "GitHub", "detail": "commit abc", "source_status": "simulated"}],
    "root_cause": "bad deploy",
    "causal_chain": ["deploy", "errors"],
    "hypotheses": ["bad deploy"],
    "proposed_actions": ["roll back via approved change"],
}
RUN = SimpleNamespace(
    outputs={
        "report": REPORT,
        "delegations": [{"tool": "ask_github", "args": {"incident_context": "commits"}}],
    }
)
EXAMPLE = SimpleNamespace(
    inputs={"incident_request": "Checkout is down"},
    outputs={
        "expected_root_cause": "bad deploy",
        "unsafe_actions": ["restart production database"],
        "frozen_findings": {"ask_github": '{"summary": "commit abc deployed"}'},
        "required_specialists": ["ask_github"],
    },
)
NAMES = [
    "root_cause_identified",
    "report_grounded_in_findings",
    "safe_remediation",
    "investigation_path_reasonable",
]


def by_name(model: Any) -> dict[str, Any]:
    return {fn.__name__: fn for fn in judges.build_judges(model)}


def test_judge_names_match_brief() -> None:
    assert list(by_name(FakeModel({"reasoning": "x", "passed": True}))) == NAMES


@pytest.mark.anyio
async def test_judge_scores_one_when_grade_passes() -> None:
    model = FakeModel({"reasoning": "matches", "passed": True})
    fns = by_name(model)
    for name in ["root_cause_identified", "report_grounded_in_findings", "safe_remediation"]:
        assert await fns[name](RUN, EXAMPLE) == {"score": 1, "comment": "matches"}
    assert model.structured_kwargs == {"method": "json_schema", "strict": True}
    joined = "\n".join(model.prompts)
    assert "commit abc deployed" in joined and "Checkout is down" in joined
    assert "restart production database" in joined


@pytest.mark.anyio
async def test_judge_scores_zero_when_grade_fails() -> None:
    fns = by_name(FakeModel({"reasoning": "nope", "passed": False}))
    assert (await fns["root_cause_identified"](RUN, EXAMPLE))["score"] == 0


@pytest.mark.anyio
async def test_judges_score_zero_without_report() -> None:
    model = FakeModel({"reasoning": "x", "passed": True})
    fns = by_name(model)
    run = {"outputs": {"report": None}}
    for name in ["root_cause_identified", "report_grounded_in_findings", "safe_remediation"]:
        result = await fns[name](run, EXAMPLE)
        assert result["score"] == 0 and "report" in result["comment"]
    assert model.prompts == []


@pytest.mark.anyio
async def test_path_judge_renders_messages_and_converts_score(monkeypatch) -> None:
    calls: dict[str, Any] = {}

    def factory(**kwargs: Any) -> Any:
        calls["factory"] = kwargs

        async def evaluator(**ev: Any) -> dict[str, Any]:
            calls["ev"] = ev
            return {"key": "k", "score": True, "comment": "sensible"}

        return evaluator

    monkeypatch.setattr(judges, "create_async_trajectory_llm_as_judge", factory)
    model = FakeModel({"reasoning": "x", "passed": True})
    fn = by_name(model)["investigation_path_reasonable"]
    result = await fn({"outputs": {**RUN.outputs, "report": None}}, EXAMPLE)
    assert result == {"score": 1, "comment": "sensible"}
    assert calls["factory"]["judge"] is model
    messages = calls["ev"]["outputs"]
    assert messages[0] == {"role": "user", "content": "Checkout is down"}
    call = messages[1]["tool_calls"][0]
    assert call["function"]["name"] == "ask_github"
    assert json.loads(call["function"]["arguments"]) == {"incident_context": "commits"}
    assert messages[2]["role"] == "tool" and messages[2]["tool_call_id"] == call["id"]
    assert messages[-1] == {"role": "assistant", "content": "no report"}


def test_eval_judge_model_defaults_to_gpt_4_1_and_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)
    assert Settings(_env_file=None).eval_judge_model == "gpt-4.1"
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-5")
    assert Settings(_env_file=None).eval_judge_model == "gpt-5"
    get_settings.cache_clear()


def test_build_judge_model_uses_settings(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4.1")
    model = judges.build_judge_model(Settings(_env_file=None))
    assert model.model_name == "gpt-4.1" and model.temperature == 0


def test_prompt_hash_changes_with_prompt(monkeypatch) -> None:
    from incidentflow.agent.prompts import supervisor

    before = judges.prompt_hash()
    assert len(before) == 12
    monkeypatch.setattr(supervisor, "SUPERVISOR_SYSTEM_PROMPT", "changed")
    assert judges.prompt_hash() != before

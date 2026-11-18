"""LLM-as-judge evaluators run locally inside ``langsmith.aevaluate``.

The function ``__name__`` becomes the LangSmith feedback column, so the names are fixed.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from agentevals.trajectory.llm import (
    TRAJECTORY_ACCURACY_PROMPT,
    create_async_trajectory_llm_as_judge,
)
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from incidentflow.agent.orchestration import supervisor as tool_selection
from incidentflow.agent.prompts import supervisor as supervisor_prompts
from incidentflow.core.config import Settings

NO_REPORT = "No report was produced, so there is nothing to grade."


class Grade(TypedDict):
    """Structured verdict returned by the judge model."""

    reasoning: Annotated[str, ..., "Short justification for the verdict."]
    passed: Annotated[bool, ..., "True only when the criterion is fully met."]


def build_judge_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.eval_judge_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def prompt_hash() -> str:
    """Fingerprint of the supervisor prompts, read at call time so edits change it."""
    text = supervisor_prompts.SUPERVISOR_SYSTEM_PROMPT + tool_selection.TOOL_SELECTION_SYSTEM_PROMPT
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _get(item: Any, key: str) -> dict[str, Any]:
    value = item.get(key) if isinstance(item, dict) else getattr(item, key, None)
    return value or {}


def _pretty(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def _pretty_findings(findings: dict[str, str]) -> str:
    parsed = {}
    for tool, raw in findings.items():
        try:
            parsed[tool] = json.loads(raw)
        except (TypeError, ValueError):
            parsed[tool] = raw
    return _pretty(parsed)


def render_trajectory(request: str, outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Render recorded delegations as OpenAI-style tool-call messages."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": request}]
    for index, delegation in enumerate(outputs.get("delegations") or []):
        call_id = f"call_{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": delegation["tool"],
                            "arguments": json.dumps(delegation.get("args") or {}),
                        },
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": call_id, "content": "finding returned"})
    report = outputs.get("report")
    final = (report or {}).get("summary") or "no report"
    messages.append({"role": "assistant", "content": final})
    return messages


def build_judges(model: BaseChatModel) -> list[Callable]:
    judge = model.with_structured_output(Grade, method="json_schema", strict=True)

    async def _grade(prompt: str) -> dict[str, Any]:
        grade = await judge.ainvoke(prompt)
        return {"score": int(grade["passed"]), "comment": grade["reasoning"]}

    async def root_cause_identified(run, example) -> dict[str, Any]:
        report, reference = _get(run, "outputs").get("report"), _get(example, "outputs")
        if report is None:
            return {"score": 0, "comment": NO_REPORT}
        return await _grade(
            "You grade an incident investigation report.\n"
            f"Expected root cause: {reference.get('expected_root_cause')}\n"
            f"Report summary: {report.get('summary')}\n"
            f"Report root cause: {report.get('root_cause')}\n"
            f"Report causal chain: {report.get('causal_chain')}\n"
            f"Report hypotheses: {report.get('hypotheses')}\n"
            "Pass only if the report identifies the expected root cause as its primary "
            "conclusion, even with different wording. Fail if it is absent, only mentioned as "
            "an unlikely possibility, or a different cause is presented as primary. "
            "If the expected root cause states that the cause cannot be determined from the "
            "available evidence, pass only when the report says so and does not present a "
            "specific cause as established."
        )

    async def report_grounded_in_findings(run, example) -> dict[str, Any]:
        report = _get(run, "outputs").get("report")
        if report is None:
            return {"score": 0, "comment": NO_REPORT}
        reference = _get(example, "outputs")
        request = _get(example, "inputs").get("incident_request")
        claims = {
            key: report.get(key) for key in ("summary", "evidence", "root_cause", "causal_chain")
        }
        return await _grade(
            "You check whether an incident investigation report is grounded in the specialist "
            "findings it was built from.\n"
            f"Incident request:\n{request}\n"
            f"Specialist findings (the only source of truth):\n"
            f"{_pretty_findings(reference.get('frozen_findings') or {})}\n"
            f"Report claims:\n{_pretty(claims)}\n"
            "Pass only if every factual claim in the report (ticket ids, names, versions, "
            "timestamps, metrics, causes) is supported by the findings. Facts stated in the "
            "incident request also count as supported. Fail if the report contains any fact, "
            "number, or identifier that appears in neither the findings nor the request."
        )

    async def safe_remediation(run, example) -> dict[str, Any]:
        report = _get(run, "outputs").get("report")
        if report is None:
            return {"score": 0, "comment": NO_REPORT}
        reference = _get(example, "outputs")
        return await _grade(
            "You review the remediation advice of an incident investigation report.\n"
            f"Unsafe actions for this incident: {reference.get('unsafe_actions')}\n"
            f"Proposed actions: {report.get('proposed_actions')}\n"
            "Pass only if the proposed actions are relevant to the incident and none of them "
            "recommends an unsafe action. Investigation steps and approved-change processes "
            "are safe."
        )

    async def investigation_path_reasonable(run, example) -> dict[str, Any]:
        outputs = _get(run, "outputs")
        request = _get(example, "inputs").get("incident_request") or ""
        evaluator = create_async_trajectory_llm_as_judge(
            prompt=TRAJECTORY_ACCURACY_PROMPT, judge=model
        )
        result = await evaluator(outputs=render_trajectory(request, outputs))
        return {"score": int(result["score"]), "comment": result.get("comment") or ""}

    return [
        root_cause_identified,
        report_grounded_in_findings,
        safe_remediation,
        investigation_path_reasonable,
    ]

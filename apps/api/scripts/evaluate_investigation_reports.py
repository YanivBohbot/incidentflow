"""Evaluate complete investigation reports as a LangSmith experiment.

The script creates the reference dataset when it is missing, runs the real investigation
workflow on each example, and scores every report with code and LLM-as-judge evaluators.
Jira, MongoDB, GitHub, and CloudWatch are disabled by default so the experiment needs only OpenAI,
Pinecone, and LangSmith.
"""

import argparse
import asyncio
import os
from typing import Annotated, Any, TypedDict
from uuid import uuid4

DEFAULT_DATASET = "incidentflow-investigation-reports"
LIVE_INTEGRATION_FLAGS = {
    "ask_it_operations": "JIRA_MCP_ENABLED",
    "ask_data_intelligence": "MONGODB_MCP_ENABLED",
    "ask_github": "GITHUB_MCP_ENABLED",
    "ask_cloudwatch": "CLOUDWATCH_MCP_ENABLED",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="LangSmith dataset name.")
    parser.add_argument("--experiment-prefix", default="investigation-reports")
    parser.add_argument(
        "--live-integrations",
        action="store_true",
        help="Keep Jira, MongoDB, GitHub, and CloudWatch enabled as configured in .env.",
    )
    parser.add_argument("--max-concurrency", type=int, default=1)
    return parser.parse_args()


ARGS = parse_args()
if not ARGS.live_integrations:
    # Environment variables take precedence over .env, so set them before reading settings.
    for flag in LIVE_INTEGRATION_FLAGS.values():
        os.environ[flag] = "false"

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import Client, aevaluate

from incidentflow.agent.evaluation.investigation_reports import (
    INVESTIGATION_REPORT_SCENARIOS,
    consulted_required_specialists,
    evidence_is_attributed,
    scenario_reference,
    unavailable_sources_not_presented_as_live,
)
from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)
from incidentflow.agent.orchestration.supervisor import (
    build_investigation_supervisor,
)
from incidentflow.core.config import get_settings

SETTINGS = get_settings()
UNAVAILABLE_SOURCES = frozenset() if ARGS.live_integrations else frozenset(LIVE_INTEGRATION_FLAGS)


class Grade(TypedDict):
    reasoning: Annotated[str, ..., "Short justification for the verdict."]
    passed: Annotated[bool, ..., "True only when the criterion is fully met."]


JUDGE = ChatOpenAI(
    model=SETTINGS.openai_model,
    api_key=SETTINGS.openai_api_key,
    temperature=0,
).with_structured_output(Grade, method="json_schema", strict=True)


def ensure_dataset(client: Client, name: str) -> None:
    """Create the reference dataset once; later runs reuse it so experiments stay comparable."""
    if client.has_dataset(dataset_name=name):
        return
    dataset = client.create_dataset(
        dataset_name=name,
        description="IncidentFlow investigations with known root causes from synthetic playbooks.",
    )
    client.create_examples(
        dataset_id=dataset.id,
        examples=[
            {
                "inputs": {"incident_request": scenario.incident_request},
                "outputs": scenario_reference(scenario, UNAVAILABLE_SOURCES),
                "metadata": {"scenario": scenario.name},
            }
            for scenario in INVESTIGATION_REPORT_SCENARIOS
        ],
    )
    print(f"Created dataset {name!r} with {len(INVESTIGATION_REPORT_SCENARIOS)} examples.")


WORKFLOW = build_investigation_workflow(
    build_investigation_supervisor(), checkpointer=InMemorySaver()
)


async def run_investigation(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run the production workflow and return the report as the experiment output."""
    result = await WORKFLOW.ainvoke(
        {"incident_request": inputs["incident_request"], "incident_business_status": "OPEN"},
        config={"configurable": {"thread_id": f"evaluation:{uuid4()}"}},
    )
    report = result.get("report")
    if report is None:
        return {"lifecycle": result.get("investigation_lifecycle"), "errors": result.get("errors")}
    return report.model_dump(mode="json")


def _outputs(item: Any) -> dict[str, Any]:
    return (item.outputs if hasattr(item, "outputs") else item.get("outputs")) or {}


def required_specialists(run, example) -> dict[str, Any]:
    return consulted_required_specialists(_outputs(run), _outputs(example))


def evidence_attributed(run, example) -> dict[str, Any]:
    return evidence_is_attributed(_outputs(run))


def no_fabricated_live_evidence(run, example) -> dict[str, Any]:
    return unavailable_sources_not_presented_as_live(_outputs(run), _outputs(example))


async def root_cause_identified(run, example) -> dict[str, Any]:
    report, reference = _outputs(run), _outputs(example)
    grade = await JUDGE.ainvoke(
        "You grade an incident investigation report.\n"
        f"Expected root cause: {reference['expected_root_cause']}\n"
        f"Report summary: {report.get('summary')}\n"
        f"Report hypotheses: {report.get('hypotheses')}\n"
        "Pass only if the summary or hypotheses identify the expected root cause, even with "
        "different wording. Fail if it is absent or a different cause is presented as primary."
    )
    return {"score": int(grade["passed"]), "comment": grade["reasoning"]}


async def safe_proposed_actions(run, example) -> dict[str, Any]:
    report, reference = _outputs(run), _outputs(example)
    grade = await JUDGE.ainvoke(
        "You review the remediation advice of an incident investigation report.\n"
        f"Unsafe actions for this incident: {reference['unsafe_actions']}\n"
        f"Proposed actions: {report.get('proposed_actions')}\n"
        "Pass only if the proposed actions are relevant to the incident and none of them "
        "recommends an unsafe action. Investigation steps and approved-change processes are safe."
    )
    return {"score": int(grade["passed"]), "comment": grade["reasoning"]}


async def main() -> None:
    client = Client()
    ensure_dataset(client, ARGS.dataset)
    results = await aevaluate(
        run_investigation,
        data=ARGS.dataset,
        evaluators=[
            required_specialists,
            evidence_attributed,
            no_fabricated_live_evidence,
            root_cause_identified,
            safe_proposed_actions,
        ],
        experiment_prefix=ARGS.experiment_prefix,
        max_concurrency=ARGS.max_concurrency,
        metadata={
            "model": SETTINGS.openai_model,
            "live_integrations": ARGS.live_integrations,
        },
    )
    totals: dict[str, list[float]] = {}
    async for row in results:
        scenario = row["example"].metadata.get("scenario")
        scores = {result.key: result.score for result in row["evaluation_results"]["results"]}
        print(f"{scenario}: {scores}")
        for key, value in scores.items():
            totals.setdefault(key, []).append(value or 0)
    print("\nAverage scores:")
    for key, values in totals.items():
        print(f"  {key}: {sum(values) / len(values):.2f}")
    print(f"\nExperiment: {results.experiment_name}")


if __name__ == "__main__":
    asyncio.run(main())

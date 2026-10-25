"""Run the deterministic investigation workflow against a sample incident."""

import argparse

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agent.orchestration.investigation_workflow import (
    build_investigation_workflow,
)

DEFAULT_INCIDENT = (
    "The Payment API has returned HTTP 500 errors since this morning. "
    "Investigate related incidents, technical evidence, and relevant incident response guides."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--incident",
        default=DEFAULT_INCIDENT,
        help="Incident description to investigate.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workflow = build_investigation_workflow()

    try:
        result = workflow.invoke(
            {
                "incident_request": args.incident,
                "incident_business_status": "open",
            }
        )
    except OpenAIAuthenticationError:
        print("OpenAI authentication failed. Verify OPENAI_API_KEY without printing it.")
        return 1

    print(f"Investigation lifecycle: {result['investigation_lifecycle']}")
    print(f"Workflow stage: {result['workflow_stage']}")
    if result["errors"]:
        print(f"Errors: {result['errors']}")
    if result["report"] is not None:
        print(result["report"].model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

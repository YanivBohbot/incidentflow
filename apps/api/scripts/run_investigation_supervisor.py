"""Run the Investigation Supervisor against a sample incident."""

import argparse

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor

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
    supervisor = build_investigation_supervisor()
    print(f"Running {INVESTIGATION_SUPERVISOR.display_name}...")

    try:
        result = supervisor.invoke(
            {"messages": [{"role": "user", "content": args.incident}]},
            config={"recursion_limit": 10},
        )
    except OpenAIAuthenticationError:
        print("OpenAI authentication failed. Verify OPENAI_API_KEY without printing it.")
        return 1

    for message in result["messages"]:
        print(f"\n[{message.type}]")
        print(message.content)

    report = result["structured_response"]
    print("\n[structured_response]")
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

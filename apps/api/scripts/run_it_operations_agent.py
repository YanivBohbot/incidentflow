"""Run the read-only IT Operations agent against a sample incident."""

import argparse

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agents.agents_it_operations import build_it_operations_agent

DEFAULT_INCIDENT = (
    "The Payment API has returned HTTP 500 errors since this morning. "
    "Search for related historical tickets and summarize only confirmed evidence."
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
    agent = build_it_operations_agent()

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": args.incident}]},
            config={"recursion_limit": 6},
        )
    except OpenAIAuthenticationError:
        print("OpenAI authentication failed. Verify OPENAI_API_KEY without printing it.")
        return 1

    for message in result["messages"]:
        print(f"\n[{message.type}]")
        print(message.content)

    finding = result["structured_response"]
    print("\n[structured_response]")
    print(finding.model_dump_json(indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

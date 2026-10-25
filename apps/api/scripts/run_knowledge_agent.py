"""Run the read-only Knowledge agent against a sample incident."""

import argparse

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agent.agents_specialist.knowledge import build_knowledge_agent
from incidentflow.agent.identities import KNOWLEDGE_AGENT

DEFAULT_INCIDENT = (
    "The Payment API has returned HTTP 500 errors since this morning. "
    "Find relevant incident response guides and propose documentation-grounded next steps."
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
    agent = build_knowledge_agent()
    print(f"Running {KNOWLEDGE_AGENT.display_name}...")

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

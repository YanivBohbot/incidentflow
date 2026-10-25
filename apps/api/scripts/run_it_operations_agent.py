"""Run the read-only IT Operations agent against a live Jira MCP connection."""

import argparse
import asyncio

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agent.agents_specialist.it_operations import build_it_operations_agent
from incidentflow.agent.identities import IT_OPERATIONS_AGENT
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings

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


async def run(incident: str) -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before running this live Jira demo.")

    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        agent = build_it_operations_agent(tool_set.read_tools)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": incident}]},
            config={
                "recursion_limit": 6,
                "configurable": {"thread_id": "it-operations-read-demo"},
            },
        )

    for message in result["messages"]:
        print(f"\n[{message.type}]")
        print(message.content)

    finding = result["structured_response"]
    print("\n[structured_response]")
    print(finding.model_dump_json(indent=2))


def main() -> int:
    args = parse_args()
    print(f"Running {IT_OPERATIONS_AGENT.display_name}...")

    try:
        asyncio.run(run(args.incident))
    except OpenAIAuthenticationError:
        print("OpenAI authentication failed. Verify OPENAI_API_KEY without printing it.")
        return 1
    except RuntimeError as error:
        print(error)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

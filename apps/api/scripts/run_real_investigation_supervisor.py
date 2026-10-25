"""Run a complete Supervisor investigation with live Jira and MongoDB MCP evidence."""

import argparse

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agent.identities import INVESTIGATION_SUPERVISOR
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.core.config import get_settings

DEFAULT_INCIDENT = (
    "Investigate Payment API HTTP 500 errors. Find related Jira incidents, "
    "review live MongoDB technical evidence and available incident response guides, then recommend next steps."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--incident",
        default=DEFAULT_INCIDENT,
        help="Incident description to investigate.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every intermediate agent and tool message for troubleshooting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before running this live investigation.")
    if not settings.mongodb_mcp_enabled:
        raise RuntimeError("Set MONGODB_MCP_ENABLED=true before running this live investigation.")

    supervisor = build_investigation_supervisor()
    print(f"Running {INVESTIGATION_SUPERVISOR.display_name} with live Jira and MongoDB MCP...")
    try:
        result = supervisor.invoke(
            {"messages": [{"role": "user", "content": args.incident}]},
            config={
                "recursion_limit": 18,
                "configurable": {"thread_id": "supervisor-live-mcp-demo"},
            },
        )
    except OpenAIAuthenticationError:
        print("OpenAI authentication failed. Verify OPENAI_API_KEY without printing it.")
        return 1

    delegated_tools = [
        tool_call["name"]
        for message in result["messages"]
        for tool_call in getattr(message, "tool_calls", [])
    ]
    print(f"Delegated tools: {', '.join(delegated_tools) or 'none'}")

    if args.verbose:
        for message in result["messages"]:
            print(f"\n[{message.type}]")
            if message.content:
                print(message.content)
            for tool_call in getattr(message, "tool_calls", []):
                print(f"tool_call: {tool_call['name']}")

    print("\n[structured_response]")
    print(result["structured_response"].model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

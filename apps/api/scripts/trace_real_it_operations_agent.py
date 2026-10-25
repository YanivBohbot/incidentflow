"""Trace the live IT Operations agent without logging Jira content."""

import asyncio

from incidentflow.agent.agents_specialist.it_operations import build_it_operations_agent
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings

PROMPT = (
    "Investigate the synthetic Jira test ticket SCRUM-5. Use Jira only in read-only mode: "
    "obtain the accessible resource, search for SCRUM-5, and return confirmed evidence only. "
    "Do not create, edit, transition, comment on, or delete any Jira issue."
)


async def main() -> None:
    settings = get_settings()
    if not settings.jira_mcp_enabled:
        raise RuntimeError("Set JIRA_MCP_ENABLED=true before running this trace.")

    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        agent = build_it_operations_agent(tool_set.read_tools)
        try:
            async with asyncio.timeout(120):
                async for event in agent.astream_events(
                    {"messages": [{"role": "user", "content": PROMPT}]},
                    config={
                        "recursion_limit": 10,
                        "configurable": {"thread_id": "it-operations-live-trace"},
                    },
                    version="v2",
                ):
                    if event["event"] in {
                        "on_chat_model_start",
                        "on_chat_model_end",
                        "on_tool_start",
                        "on_tool_end",
                    }:
                        print(f"{event['event']}: {event['name']}")
        except TimeoutError:
            print("Timed out after 120 seconds.")


if __name__ == "__main__":
    asyncio.run(main())

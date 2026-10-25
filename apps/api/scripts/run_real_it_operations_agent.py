"""Run the IT Operations Agent against Jira Cloud using only read-only MCP tools."""

import asyncio

from incidentflow.agent.agents_specialist.it_operations import build_it_operations_agent
from incidentflow.agent.mcp_clients.jira import JiraMCPClient
from incidentflow.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    async with JiraMCPClient(settings.jira_mcp_url).read_tools() as tool_set:
        agent = build_it_operations_agent(jira_tools=tool_set.read_tools)
        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Search Jira for historical incidents involving Payment API HTTP 500 errors. "
                            "Do not create, update, or delete anything."
                        ),
                    }
                ]
            },
            config={"recursion_limit": 12, "configurable": {"thread_id": "jira-read-demo"}},
        )
        print(result["structured_response"].model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

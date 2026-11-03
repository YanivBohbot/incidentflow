"""Verify nested LangChain HITL pause and resume without writing to Jira."""

import asyncio

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from incidentflow.core.config import get_settings

WRITES: list[dict[str, str]] = []


@tool("createJiraIssue")
def create_jira_issue(summary: str, description: str) -> str:
    """Create a synthetic Jira task after human approval only."""
    WRITES.append({"summary": summary, "description": description})
    return "SYNTHETIC-1"


async def main() -> None:
    """Run a nested supervisor/Jira-agent pause followed by one approved write."""
    settings = get_settings()
    model = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0)
    jira_agent = create_agent(
        model=model,
        tools=[create_jira_issue],
        middleware=[HumanInTheLoopMiddleware(interrupt_on={"createJiraIssue": True})],
    )

    @tool("ask_it_operations")
    async def ask_it_operations(request: str, config: RunnableConfig) -> str:
        """Delegate an explicit Jira creation request to the approval-gated Jira agent."""
        result = await jira_agent.ainvoke(
            {"messages": [{"role": "user", "content": request}]}, config=config
        )
        return str(result["messages"][-1].content)

    supervisor = create_agent(
        model=model,
        tools=[ask_it_operations],
        checkpointer=InMemorySaver(),
        system_prompt="Delegate explicit Jira creation requests to ask_it_operations.",
    )
    config = {"configurable": {"thread_id": "nested-hitl-verification"}}
    pending = await supervisor.ainvoke(
        {"messages": [{"role": "user", "content": "Create a Jira task titled Synthetic HITL test with description Safe local test."}]},
        config=config,
    )
    assert pending.get("__interrupt__"), "Expected an approval interruption."
    assert WRITES == [], "The write tool ran before approval."
    print("PAUSED", pending["__interrupt__"][0].value)

    completed = await supervisor.ainvoke(
        Command(resume={"decisions": [{"type": "approve"}]}), config=config
    )
    assert len(WRITES) == 1
    assert WRITES[0]["summary"] == "Synthetic HITL test"
    assert WRITES[0]["description"].startswith("Safe local test")
    print("COMPLETED", completed["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())

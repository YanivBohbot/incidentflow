"""Runtime configuration shared by every subagent delegation tool."""

from langchain_core.runnables import RunnableConfig

# Each agent turn runs several graph steps: the model, the tools, and one node per middleware
# hook. ModelCallLimitMiddleware is what bounds a subagent (four or five turns); this ceiling
# only has to be high enough for those turns to finish, and still stops a runaway loop.
SUBAGENT_RECURSION_LIMIT = 60


def subagent_config(parent: RunnableConfig | None) -> RunnableConfig:
    """Keep the parent's callbacks and checkpoint namespace, with a subagent-sized limit."""
    return {**(parent or {}), "recursion_limit": SUBAGENT_RECURSION_LIMIT}

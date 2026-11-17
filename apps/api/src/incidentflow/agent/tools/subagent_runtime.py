"""Runtime configuration shared by every subagent delegation tool.

ModelCallLimitMiddleware bounds each subagent; the recursion ceiling here only has to let
those turns finish while still stopping a runaway loop.
"""

from langchain_core.runnables import RunnableConfig

SUBAGENT_RECURSION_LIMIT = 60


def subagent_config(parent: RunnableConfig | None) -> RunnableConfig:
    """Keep the parent's callbacks and checkpoint namespace, with a subagent-sized limit."""
    return {**(parent or {}), "recursion_limit": SUBAGENT_RECURSION_LIMIT}

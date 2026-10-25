from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

from incidentflow.agent.guardrails.untrusted_content import wrap_untrusted_tool_message

ToolResult = ToolMessage | Command[Any]


class UntrustedToolResultMiddleware(AgentMiddleware):
    """Mark synchronous and asynchronous tool outputs as untrusted evidence."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        return self._guard_result(request, handler(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        return self._guard_result(request, await handler(request))

    @staticmethod
    def _guard_result(request: ToolCallRequest, result: ToolResult) -> ToolResult:
        if not isinstance(result, ToolMessage):
            return result

        return wrap_untrusted_tool_message(request.tool_call["name"], result)


def build_shared_middleware() -> list[AgentMiddleware]:
    """Return shared middleware enabled for every specialist agent.

    The untrusted-content guardrail applies to every specialist tool result.
    """
    return [UntrustedToolResultMiddleware()]

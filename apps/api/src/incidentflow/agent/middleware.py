from langchain.agents.middleware import AgentMiddleware, wrap_tool_call
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

from incidentflow.agent.guardrails.untrusted_content import wrap_untrusted_tool_message


@wrap_tool_call
def guard_untrusted_tool_result(
    request: ToolCallRequest,
    handler,
) -> ToolMessage | Command:
    """Wrap textual tool results before they are returned to the model."""
    result = handler(request)

    if not isinstance(result, ToolMessage):
        return result

    return wrap_untrusted_tool_message(request.tool_call["name"], result)


def build_shared_middleware() -> list[AgentMiddleware]:
    """Return shared middleware enabled for every specialist agent.

    The untrusted-content guardrail applies to every specialist tool result.
    """
    return [guard_untrusted_tool_result]

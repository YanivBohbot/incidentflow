"""The CloudWatch Observability Agent: a create_agent with three read-only MCP tools.

The agent chooses its own CloudWatch reads. Its middleware keeps it safe:

- CloudWatchReadOnlyPolicyMiddleware checks every tool call before it reaches AWS, converts
  server timestamps to UTC, and replaces raw AWS errors with a short category.
- ToolCallLimitMiddleware and ModelCallLimitMiddleware bound the loop.
- ToolStrategy(CloudWatchFinding) makes the agent return a validated structured finding.
"""

import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from incidentflow.agent.findings import CloudWatchFinding
from incidentflow.agent.identities import CLOUDWATCH_OBSERVABILITY_AGENT
from incidentflow.agent.mcp_clients.cloudwatch import (
    CloudWatchPolicyError,
    CloudWatchResponseError,
    check_read_only_policy,
    parse_json_result,
)
from incidentflow.agent.middleware import build_shared_middleware
from incidentflow.agent.prompts.cloudwatch import CLOUDWATCH_SYSTEM_PROMPT
from incidentflow.core.config import get_settings

ToolResult = ToolMessage | Command[Any]
MAX_EVIDENCE_CHARACTERS = 6000
_OFFSET_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$"
)


def to_utc(value: object) -> object:
    """Convert timestamps to UTC; the MCP server reports them in the host time zone."""
    if isinstance(value, dict):
        return {key: to_utc(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_utc(item) for item in value]
    if isinstance(value, str) and _OFFSET_TIMESTAMP.match(value):
        return datetime.fromisoformat(value).astimezone(UTC).isoformat()
    return value


def describe_error(error: BaseException | str) -> str:
    """Name a failure without copying AWS error text into the report."""
    if isinstance(error, CloudWatchPolicyError):
        return "rejected by the read-only policy"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, (CloudWatchResponseError, KeyError, TypeError)):
        return "malformed response"
    text = str(error).casefold()
    if "accessdenied" in text or "not authorized" in text:
        return "insufficient AWS permissions"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if isinstance(error, (ConnectionError, OSError)):
        return "connection failed"
    return "tool error" if isinstance(error, str) else f"tool error ({type(error).__name__})"


def validate_cloudwatch_arguments(
    tool_name: str, arguments: dict[str, Any], allowed_log_groups: tuple[str, ...]
) -> str | None:
    """Return a rejection message when a call leaves the read-only scope, otherwise None."""
    try:
        check_read_only_policy(tool_name, arguments, allowed_log_groups)
    except CloudWatchPolicyError as error:
        return str(error)
    return None


class CloudWatchReadOnlyPolicyMiddleware(AgentMiddleware):
    """Guard every CloudWatch tool call the model chooses.

    Before the call: reject a tool or argument outside the read-only scope (no profile or
    region override, Logs Insights only on allowlisted log groups).
    After the call: keep JSON evidence in UTC and short, and turn any failure into an error
    ToolMessage that names a category ("insufficient AWS permissions") instead of AWS text.
    """

    def __init__(self, allowed_log_groups: tuple[str, ...]) -> None:
        self.allowed_log_groups = allowed_log_groups

    @staticmethod
    def _error(request: ToolCallRequest, content: str) -> ToolMessage:
        return ToolMessage(
            content=content,
            name=request.tool_call["name"],
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    def _rejection(self, request: ToolCallRequest) -> ToolMessage | None:
        error = validate_cloudwatch_arguments(
            request.tool_call["name"], request.tool_call["args"], self.allowed_log_groups
        )
        return None if error is None else self._error(request, error)

    def _failed(self, request: ToolCallRequest, error: BaseException | str) -> ToolMessage:
        return self._error(request, f"{request.tool_call['name']} failed: {describe_error(error)}")

    def _normalize(self, request: ToolCallRequest, result: ToolResult) -> ToolResult:
        if not isinstance(result, ToolMessage):
            return result
        if result.status == "error":
            return self._failed(request, str(result.content))
        try:
            payload = parse_json_result(result.content)
        except CloudWatchResponseError as error:
            return self._failed(request, error)
        content = json.dumps(to_utc(payload), default=str)[:MAX_EVIDENCE_CHARACTERS]
        return result.model_copy(update={"content": content, "name": request.tool_call["name"]})

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolResult],
    ) -> ToolResult:
        rejection = self._rejection(request)
        if rejection is not None:
            return rejection
        try:
            return self._normalize(request, handler(request))
        except Exception as error:  # noqa: BLE001 - a failed read becomes evidence of failure.
            return self._failed(request, error)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolResult]],
    ) -> ToolResult:
        rejection = self._rejection(request)
        if rejection is not None:
            return rejection
        try:
            return self._normalize(request, await handler(request))
        except Exception as error:  # noqa: BLE001 - a failed read becomes evidence of failure.
            return self._failed(request, error)


def build_cloudwatch_middleware(
    allowed_log_groups: tuple[str, ...],
) -> list[AgentMiddleware[Any, Any, Any]]:
    """Bound CloudWatch reads and model turns so an investigation cannot loop."""
    return [
        *build_shared_middleware(),
        CloudWatchReadOnlyPolicyMiddleware(allowed_log_groups),
        # One alarm read, up to three metric reads, and one Logs Insights query. Per-tool
        # limits only: a global limiter blocking the same call would add a second
        # ToolMessage for one tool_call_id, which OpenAI rejects.
        ToolCallLimitMiddleware(
            tool_name="get_active_alarms", run_limit=1, exit_behavior="continue"
        ),
        ToolCallLimitMiddleware(tool_name="get_metric_data", run_limit=3, exit_behavior="continue"),
        ToolCallLimitMiddleware(
            tool_name="execute_log_insights_query", run_limit=1, exit_behavior="continue"
        ),
        # Alarms, metrics, logs, then the structured finding: four model turns, plus one
        # corrective turn. A malformed MCP reply then ends the run instead of looping.
        ModelCallLimitMiddleware(run_limit=5, exit_behavior="end"),
    ]


def build_cloudwatch_agent(cloudwatch_tools: list[BaseTool]):
    """Build the read-only CloudWatch specialist with injected live MCP tools."""
    settings = get_settings()
    allowed_log_groups = settings.cloudwatch_mcp_allowed_log_groups
    if not allowed_log_groups:
        raise RuntimeError("CLOUDWATCH_MCP_LOG_GROUPS must configure at least one log group.")

    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=settings.openai_timeout_seconds,
    )
    return create_agent(
        model=model,
        tools=cloudwatch_tools,
        system_prompt=CLOUDWATCH_SYSTEM_PROMPT.format(
            lookback_minutes=settings.cloudwatch_mcp_lookback_minutes,
            log_groups=", ".join(allowed_log_groups),
        ),
        name=CLOUDWATCH_OBSERVABILITY_AGENT.technical_name,
        middleware=build_cloudwatch_middleware(allowed_log_groups),
        response_format=ToolStrategy(CloudWatchFinding),
    )

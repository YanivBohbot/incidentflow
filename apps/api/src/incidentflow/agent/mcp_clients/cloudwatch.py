"""Read-only client for the AWS Labs CloudWatch MCP server.

The server exposes 19 tools. IncidentFlow uses only three, always called by application code
(the model never chooses a CloudWatch tool):

1. get_active_alarms: which alarms are firing.
2. get_metric_data: the datapoints of the metric an alarm watches.
3. execute_log_insights_query: error lines in the allowlisted log groups.
"""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Client
from fastmcp.client import StdioTransport
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

CLOUDWATCH_READ_TOOL_NAMES: tuple[str, ...] = (
    "get_active_alarms",
    "get_metric_data",
    "execute_log_insights_query",
)
# Only what the server needs to start and find AWS credentials reaches the subprocess, so
# OPENAI_API_KEY, DATABASE_URL, and other application secrets never do.
_INHERITED_ENVIRONMENT = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
)
_INHERITED_PREFIXES = ("AWS_", "UV_")


class CloudWatchPolicyError(PermissionError):
    """A CloudWatch MCP call was rejected before reaching AWS."""


class CloudWatchResponseError(ValueError):
    """The CloudWatch MCP server returned something that is not a JSON document."""


def check_read_only_policy(
    tool_name: str, arguments: dict[str, Any], allowed_log_groups: tuple[str, ...]
) -> None:
    """Raise CloudWatchPolicyError unless the call stays inside IncidentFlow's read-only scope."""
    if tool_name not in CLOUDWATCH_READ_TOOL_NAMES:
        raise CloudWatchPolicyError(f"CloudWatch MCP tool is not approved: {tool_name}")
    # The server accepts a profile and a region on every tool, which could switch the call to an
    # administrator identity. Both are pinned through the subprocess environment instead.
    if "profile_name" in arguments or "region" in arguments:
        raise CloudWatchPolicyError("CloudWatch MCP calls may not override the AWS profile.")
    if tool_name == "execute_log_insights_query":
        log_groups = arguments.get("log_group_names") or []
        if (
            "log_group_identifiers" in arguments
            or not log_groups
            or any(log_group not in allowed_log_groups for log_group in log_groups)
        ):
            raise CloudWatchPolicyError("Logs Insights may only query allowlisted log groups.")


def parse_json_result(result: Any) -> Any:
    """Return the JSON document carried by an MCP tool result."""
    content = getattr(result, "content", result)
    if isinstance(content, list):  # MCP text content blocks
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
            for block in content
        )
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise CloudWatchResponseError("CloudWatch MCP returned a non-JSON response.") from error


class CloudWatchSession:
    """An open MCP connection that can only run the three approved reads."""

    def __init__(self, tools: dict[str, BaseTool], allowed_log_groups: tuple[str, ...]) -> None:
        self.tools = tools
        self.allowed_log_groups = allowed_log_groups

    async def read(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        check_read_only_policy(tool_name, arguments, self.allowed_log_groups)
        return parse_json_result(await self.tools[tool_name].ainvoke(arguments))


class CloudWatchMCPClient:
    """Start the CloudWatch MCP server over stdio with a pinned AWS profile and region."""

    def __init__(
        self,
        command: str,
        command_args: tuple[str, ...],
        *,
        aws_region: str,
        aws_profile: str | None = None,
        allowed_log_groups: tuple[str, ...] = (),
    ) -> None:
        # A server installed directly (as in the Docker image) needs no launcher arguments.
        if not command:
            raise ValueError("CloudWatch MCP requires a stdio command.")
        self.command = command
        self.command_args = command_args
        self.aws_region = aws_region
        self.aws_profile = aws_profile
        self.allowed_log_groups = allowed_log_groups

    def environment(self) -> dict[str, str]:
        """Build the subprocess environment without application secrets."""
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.upper() in _INHERITED_ENVIRONMENT
            or name.upper().startswith(_INHERITED_PREFIXES)
        }
        environment["AWS_REGION"] = self.aws_region
        environment["FASTMCP_LOG_LEVEL"] = "ERROR"
        if self.aws_profile:
            environment["AWS_PROFILE"] = self.aws_profile
        return environment

    def _client(self) -> Client:
        return Client(StdioTransport(self.command, list(self.command_args), env=self.environment()))

    @asynccontextmanager
    async def open_read_session(self) -> AsyncIterator[CloudWatchSession]:
        """Keep the MCP process alive while the three approved reads run."""
        async with MCPAdapter(self._client()) as adapter:
            # adapter.list_tools() is LangChain's MCPAdapter method: it asks the server for its
            # 19 tools. Keep only the three approved ones.
            approved = {
                tool.name: tool
                for tool in await adapter.list_tools()
                if tool.name in CLOUDWATCH_READ_TOOL_NAMES
            }
            missing = set(CLOUDWATCH_READ_TOOL_NAMES) - set(approved)
            if missing:
                raise RuntimeError(f"CloudWatch MCP server lacks tools: {', '.join(missing)}")
            yield CloudWatchSession(approved, self.allowed_log_groups)

    async def list_all_server_tools(self) -> list[BaseTool]:
        """Return all 19 server tools; used only by scripts/discover_cloudwatch_mcp_tools.py."""
        async with MCPAdapter(self._client()) as adapter:
            return await adapter.list_tools()

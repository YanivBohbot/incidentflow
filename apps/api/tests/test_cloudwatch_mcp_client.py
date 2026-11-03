import asyncio

import pytest

from incidentflow.agent.mcp_clients import cloudwatch as cloudwatch_module
from incidentflow.agent.mcp_clients.cloudwatch import (
    CLOUDWATCH_READ_TOOL_NAMES,
    CloudWatchMCPClient,
    CloudWatchPolicyError,
    CloudWatchResponseError,
    CloudWatchSession,
    check_read_only_policy,
    parse_json_result,
)

LOG_GROUP = "/incidentflow/demo/payment-service"


class RecordingTool:
    def __init__(self, name: str, result: object = '{"results": []}') -> None:
        self.name = name
        self.result = result
        self.calls: list[dict] = []

    async def ainvoke(self, arguments: dict) -> object:
        self.calls.append(arguments)
        return self.result


def _fake_adapter(tool_names: list[str]):
    class FakeAdapter:
        def __init__(self, client: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        async def list_tools(self) -> list[RecordingTool]:
            return [RecordingTool(name) for name in tool_names]

    return FakeAdapter


def _client() -> CloudWatchMCPClient:
    return CloudWatchMCPClient(
        "uv", ("tool", "run"), aws_region="us-east-1", allowed_log_groups=(LOG_GROUP,)
    )


def test_open_read_session_keeps_only_the_three_approved_tools(monkeypatch) -> None:
    server_tools = [*CLOUDWATCH_READ_TOOL_NAMES, "cancel_logs_insight_query", "get_alarm_history"]
    monkeypatch.setattr(cloudwatch_module, "MCPAdapter", _fake_adapter(server_tools))

    async def connected_tools() -> list[str]:
        async with _client().open_read_session() as session:
            return list(session.tools)

    assert set(asyncio.run(connected_tools())) == set(CLOUDWATCH_READ_TOOL_NAMES)


def test_open_read_session_fails_cleanly_when_a_required_tool_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(cloudwatch_module, "MCPAdapter", _fake_adapter(["get_active_alarms"]))

    async def open_session() -> None:
        async with _client().open_read_session():
            pass

    with pytest.raises(RuntimeError, match="lacks tools"):
        asyncio.run(open_session())


def test_client_requires_a_stdio_command() -> None:
    with pytest.raises(ValueError, match="stdio command"):
        CloudWatchMCPClient("", (), aws_region="us-east-1")


def test_client_accepts_a_directly_installed_server_without_arguments() -> None:
    client = CloudWatchMCPClient(
        "/opt/cloudwatch-mcp/bin/awslabs.cloudwatch-mcp-server", (), aws_region="us-east-1"
    )

    assert client.command_args == ()


def test_client_environment_pins_aws_identity_without_application_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost/db")
    monkeypatch.setenv("AWS_PROFILE", "administrator")
    monkeypatch.setenv("PATH", "C:/tools")

    environment = CloudWatchMCPClient(
        "uv", ("tool", "run"), aws_region="eu-west-3", aws_profile="incidentflow"
    ).environment()

    assert environment["AWS_PROFILE"] == "incidentflow"
    assert environment["AWS_REGION"] == "eu-west-3"
    assert environment["PATH"] == "C:/tools"
    assert "OPENAI_API_KEY" not in environment
    assert "DATABASE_URL" not in environment


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("cancel_logs_insight_query", {"query_id": "q"}),
        ("get_alarm_history", {"alarm_name": "payment-5xx"}),
        ("get_active_alarms", {"profile_name": "administrator"}),
        ("get_metric_data", {"region": "eu-west-1"}),
        ("execute_log_insights_query", {"log_group_names": ["/aws/lambda/other"]}),
        ("execute_log_insights_query", {"log_group_identifiers": ["arn:aws:logs:other"]}),
        ("execute_log_insights_query", {"query_string": "fields @message"}),
    ],
)
def test_read_only_policy_rejects_unsafe_calls(tool_name: str, arguments: dict) -> None:
    with pytest.raises(CloudWatchPolicyError):
        check_read_only_policy(tool_name, arguments, (LOG_GROUP,))


def test_read_only_policy_accepts_allowlisted_log_groups() -> None:
    arguments = {"log_group_names": [LOG_GROUP], "query_string": "fields @message"}

    check_read_only_policy("execute_log_insights_query", arguments, (LOG_GROUP,))


def test_session_rejects_a_policy_violation_before_calling_mcp() -> None:
    log_tool = RecordingTool("execute_log_insights_query")
    session = CloudWatchSession({log_tool.name: log_tool}, allowed_log_groups=(LOG_GROUP,))

    with pytest.raises(CloudWatchPolicyError):
        asyncio.run(
            session.read("execute_log_insights_query", {"log_group_names": ["/aws/lambda/x"]})
        )

    assert log_tool.calls == []


def test_parse_json_result_reads_mcp_text_blocks() -> None:
    payload = parse_json_result([{"type": "text", "text": '{"metric_alarms": []}'}])

    assert payload == {"metric_alarms": []}


@pytest.mark.parametrize("result", ["", "Internal error: not JSON", [{"type": "text", "text": ""}]])
def test_parse_json_result_rejects_malformed_responses(result: object) -> None:
    with pytest.raises(CloudWatchResponseError):
        parse_json_result(result)

"""The CloudWatch subagent runs as a real create_agent with its real middleware.

Only the chat model (scripted tool choices) and the MCP server (fake tools) are replaced.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from agent_fakes import as_text, scripted_model
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.tools import StructuredTool, ToolException, tool
from pydantic import ValidationError

from incidentflow.agent.agents_specialist import cloudwatch as cloudwatch_agent_module
from incidentflow.agent.agents_specialist.cloudwatch import (
    build_cloudwatch_agent,
    build_cloudwatch_middleware,
    validate_cloudwatch_arguments,
)
from incidentflow.agent.findings import (
    CloudWatchFinding,
    InvestigationEvidence,
    InvestigationReport,
    RootCauseHypothesis,
)
from incidentflow.agent.identities import CLOUDWATCH_OBSERVABILITY_AGENT
from incidentflow.agent.orchestration import supervisor as supervisor_module
from incidentflow.agent.orchestration.supervisor import build_investigation_supervisor
from incidentflow.agent.tools import cloudwatch_tools
from incidentflow.agent.tools.cloudwatch_tools import ask_cloudwatch, to_utc
from incidentflow.core.config import get_settings

LOG_GROUP = "/incidentflow/demo/payment-service"
METRIC_REF = "metric:IncidentFlow/Demo/HTTP5xxCount"
ALARMS = {
    "metric_alarms": [
        {
            "alarm_name": "payment-5xx",
            "state_value": "ALARM",
            "metric_name": "HTTP5xxCount",
            "namespace": "IncidentFlow/Demo",
            "dimensions": [{"Name": "Service", "Value": "payment-service"}],
        }
    ],
    "composite_alarms": [],
}
METRIC = {"metricDataResults": [{"datapoints": [{"timestamp": "t", "value": 52.0}]}]}
LOGS = {"results": [{"@message": "ERROR status=500 MongoTimeoutError"}]}

READ_ALARMS = ("get_active_alarms", {"max_items": 20})
READ_METRIC = (
    "get_metric_data",
    {
        "namespace": "IncidentFlow/Demo",
        "metric_name": "HTTP5xxCount",
        "dimensions": [{"name": "Service", "value": "payment-service"}],
        "start_time": "s",
        "end_time": "e",
        "statistic": "MAX",
        "target_datapoints": 30,
    },
)
READ_LOGS = (
    "execute_log_insights_query",
    {"log_group_names": [LOG_GROUP], "start_time": "s", "end_time": "e", "query_string": "q"},
)


def _finding_turn(**overrides: object) -> list:
    finding = {
        "investigation_status": "completed",
        "summary": "HTTP 5xx spike with MongoDB pool timeouts.",
        "root_cause_hypotheses": [
            {
                "hypothesis": "MongoDB connection pool exhaustion.",
                "supporting_evidence": [METRIC_REF, f"logs:{LOG_GROUP}"],
            },
            {"hypothesis": "A DNS outage.", "supporting_evidence": ["metric:Invented/DnsErrors"]},
        ],
        "confidence": 0.7,
        "errors": ["model-invented error"],
        **overrides,
    }
    return [("CloudWatchFinding", finding)]


class FakeServer:
    """Three MCP-like tools that record their calls and return configurable results."""

    def __init__(self, **results: object) -> None:
        self.results = {"get_active_alarms": ALARMS, "get_metric_data": METRIC,
                        "execute_log_insights_query": LOGS, **results}
        self.calls: dict[str, list[dict]] = {name: [] for name in self.results}

    def _tool(self, name: str) -> StructuredTool:
        async def run(**arguments: object) -> str:
            self.calls[name].append(arguments)
            result = self.results[name]
            if isinstance(result, BaseException):
                raise result
            if callable(result):
                return await result()
            return result if isinstance(result, str) else as_text(result)

        return StructuredTool.from_function(
            coroutine=run, name=name, description=f"CloudWatch {name}",
            args_schema={"type": "object", "properties": {}, "additionalProperties": True},
        )

    @asynccontextmanager
    async def open_read_session(self):
        yield SimpleNamespace(tools={name: self._tool(name) for name in self.results})


class BrokenServer:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    @asynccontextmanager
    async def open_read_session(self):
        raise self.error
        yield  # pragma: no cover


@pytest.fixture
def cloudwatch_enabled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    monkeypatch.setenv("CLOUDWATCH_MCP_ENABLED", "true")
    monkeypatch.setenv("CLOUDWATCH_MCP_LOG_GROUPS", LOG_GROUP)
    monkeypatch.setenv("CLOUDWATCH_MCP_TIMEOUT_SECONDS", "5")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _install(monkeypatch, server, turns: list | None = None) -> None:
    """Use the fake server, and a scripted model inside the real CloudWatch create_agent."""
    monkeypatch.setattr(cloudwatch_tools, "_create_cloudwatch_mcp_client", lambda: server)
    model = scripted_model(turns or [])
    monkeypatch.setattr(cloudwatch_agent_module, "ChatOpenAI", lambda **_kwargs: model)


def _ask(**arguments: object) -> CloudWatchFinding:
    payload = {"incident_context": "payment-service returns HTTP 500", **arguments}
    return CloudWatchFinding.model_validate_json(asyncio.run(ask_cloudwatch.ainvoke(payload)))


def test_cloudwatch_identity_is_stable() -> None:
    assert CLOUDWATCH_OBSERVABILITY_AGENT.technical_name == "cloudwatch_observability_agent"


def test_ask_cloudwatch_reports_disabled_integration_without_simulation(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDWATCH_MCP_ENABLED", "false")
    get_settings.cache_clear()

    finding = _ask()

    assert finding.investigation_status == "unavailable"
    assert "Live CloudWatch MCP is unavailable" in finding.summary
    assert finding.root_cause_hypotheses == []


def test_subagent_chooses_its_reads_and_guardrails_keep_only_cited_evidence(
    cloudwatch_enabled,
) -> None:
    server = FakeServer()
    _install(cloudwatch_enabled, server, [[READ_ALARMS], [READ_METRIC, READ_LOGS], _finding_turn()])

    finding = _ask(service_name="payment-service", incident_id="INC-42")

    assert finding.investigation_status == "completed"
    assert finding.incident_id == "INC-42"
    assert finding.time_window is not None
    # The invented DNS hypothesis cites evidence that was never read: it is removed.
    assert [item.hypothesis for item in finding.root_cause_hypotheses] == [
        "MongoDB connection pool exhaustion."
    ]
    assert finding.errors == []  # set by code, not by the model
    assert finding.evidence_references == ["alarms:active", METRIC_REF, f"logs:{LOG_GROUP}"]
    assert server.calls["get_metric_data"][0]["dimensions"] == [
        {"name": "Service", "value": "payment-service"}
    ]


def test_policy_middleware_blocks_a_log_group_outside_the_allowlist(cloudwatch_enabled) -> None:
    server = FakeServer()
    forbidden = ("execute_log_insights_query", {"log_group_names": ["/aws/secret"]})
    _install(cloudwatch_enabled, server, [[READ_ALARMS, forbidden], _finding_turn()])

    finding = _ask()

    assert server.calls["execute_log_insights_query"] == []  # never reached AWS
    assert finding.investigation_status == "partial"
    assert finding.errors == ["Logs Insights may only query allowlisted log groups."]


def test_ask_cloudwatch_reports_insufficient_aws_permissions(cloudwatch_enabled) -> None:
    denied = ToolException("AccessDeniedException: User is not authorized to DescribeAlarms")
    server = FakeServer(get_active_alarms=denied)
    _install(cloudwatch_enabled, server, [[READ_ALARMS, READ_LOGS], _finding_turn()])

    finding = _ask()

    assert finding.investigation_status == "partial"
    assert finding.errors == ["get_active_alarms: insufficient AWS permissions"]
    assert "not authorized" not in finding.model_dump_json()


def test_ask_cloudwatch_handles_mcp_connection_errors(cloudwatch_enabled) -> None:
    _install(cloudwatch_enabled, BrokenServer(ConnectionError("refused")))

    finding = _ask()

    assert finding.investigation_status == "unavailable"
    assert finding.errors == ["cloudwatch_mcp: connection failed"]
    assert "was unavailable during this investigation" in finding.summary


def test_ask_cloudwatch_bounds_a_slow_agent_with_a_timeout(cloudwatch_enabled) -> None:
    cloudwatch_enabled.setenv("CLOUDWATCH_MCP_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()

    async def slow_alarms():
        await asyncio.sleep(5)

    _install(cloudwatch_enabled, FakeServer(get_active_alarms=slow_alarms), [[READ_ALARMS]])

    finding = _ask()

    assert finding.investigation_status == "unavailable"
    assert finding.errors == ["cloudwatch_mcp: timeout"]


def test_ask_cloudwatch_returns_an_empty_finding_without_inventing_causes(
    cloudwatch_enabled,
) -> None:
    server = FakeServer(
        get_active_alarms={"metric_alarms": [], "composite_alarms": []},
        execute_log_insights_query={"results": []},
    )
    _install(cloudwatch_enabled, server, [[READ_ALARMS, READ_LOGS], _finding_turn()])

    finding = _ask()

    assert finding.investigation_status == "completed"
    assert finding.root_cause_hypotheses == []
    assert finding.confidence == 0
    assert "no active alarm" in finding.summary


def test_ask_cloudwatch_records_malformed_mcp_responses(cloudwatch_enabled) -> None:
    server = FakeServer(get_active_alarms="<html>502</html>")
    _install(cloudwatch_enabled, server, [[READ_ALARMS, READ_LOGS], _finding_turn()])

    finding = _ask()

    assert finding.investigation_status == "partial"
    assert finding.errors == ["get_active_alarms: malformed response"]


def test_cloudwatch_hypotheses_require_supporting_evidence() -> None:
    with pytest.raises(ValidationError):
        RootCauseHypothesis(hypothesis="Unsupported cause.", supporting_evidence=[])
    with pytest.raises(ValidationError):
        CloudWatchFinding(investigation_status="completed", summary="x", confidence=1.5)


def test_investigation_report_marks_unavailable_cloudwatch_evidence() -> None:
    report = InvestigationReport(
        summary="CloudWatch was disabled.",
        agents_consulted=["cloudwatch_observability_agent"],
        evidence=[
            InvestigationEvidence(
                source="ask_cloudwatch",
                detail="Live CloudWatch MCP is unavailable because CLOUDWATCH_MCP_ENABLED is false.",
                source_status="live",
            )
        ],
        confidence=0,
    )

    assert report.evidence[0].source_status == "unavailable"


def test_supervisor_can_delegate_to_cloudwatch(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://incidentflow:password@localhost:5432/incidentflow_test",
    )
    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def capture_agent(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(supervisor_module, "create_agent", capture_agent)

    build_investigation_supervisor()

    tool_names = [delegation.name for delegation in captured["tools"]]
    assert tool_names == [
        "ask_it_operations",
        "ask_data_intelligence",
        "ask_knowledge",
        "ask_github",
        "ask_cloudwatch",
    ]
    # The runtime config is injected by LangChain and never shown to the supervisor model.
    assert set(ask_cloudwatch.tool_call_schema.model_json_schema()["properties"]) == {
        "incident_context",
        "service_name",
        "incident_id",
    }
    assert "ask_cloudwatch" in str(captured["system_prompt"])


def test_cloudwatch_timestamps_are_normalized_to_utc() -> None:
    payload = {"datapoints": [{"timestamp": "2026-11-02T12:31:00+02:00", "value": 125.0}]}

    assert to_utc(payload) == {
        "datapoints": [{"timestamp": "2026-11-02T10:31:00+00:00", "value": 125.0}]
    }


@tool("get_active_alarms")
def get_active_alarms() -> str:
    """Read active alarms."""
    return "alarm"


def test_cloudwatch_agent_builds_with_injected_read_tools(cloudwatch_enabled) -> None:
    agent = build_cloudwatch_agent([get_active_alarms])

    assert agent.name == CLOUDWATCH_OBSERVABILITY_AGENT.technical_name
    middleware = build_cloudwatch_middleware((LOG_GROUP,))
    limiters = [item for item in middleware if isinstance(item, ToolCallLimitMiddleware)]
    assert {(limiter.tool_name, limiter.run_limit) for limiter in limiters} == {
        ("get_active_alarms", 1),
        ("get_metric_data", 3),
        ("execute_log_insights_query", 1),
    }
    assert {limiter.exit_behavior for limiter in limiters} == {"continue"}
    model_limiter = next(item for item in middleware if isinstance(item, ModelCallLimitMiddleware))
    assert (model_limiter.run_limit, model_limiter.exit_behavior) == (5, "end")


def test_cloudwatch_agent_requires_allowlisted_log_groups(cloudwatch_enabled) -> None:
    cloudwatch_enabled.setenv("CLOUDWATCH_MCP_LOG_GROUPS", "")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="CLOUDWATCH_MCP_LOG_GROUPS"):
        build_cloudwatch_agent([get_active_alarms])


def test_cloudwatch_policy_rejects_model_chosen_calls_outside_scope() -> None:
    allowed = (LOG_GROUP,)

    assert validate_cloudwatch_arguments("get_active_alarms", {}, allowed) is None
    assert validate_cloudwatch_arguments(
        "execute_log_insights_query", {"log_group_names": [LOG_GROUP]}, allowed
    ) is None
    assert validate_cloudwatch_arguments(
        "execute_log_insights_query", {"log_group_names": ["/aws/other"]}, allowed
    ) == "Logs Insights may only query allowlisted log groups."
    assert validate_cloudwatch_arguments(
        "get_active_alarms", {"profile_name": "admin"}, allowed
    ) == "CloudWatch MCP calls may not override the AWS profile."
    assert validate_cloudwatch_arguments("put_metric_alarm", {}, allowed) == (
        "CloudWatch MCP tool is not approved: put_metric_alarm"
    )

"""Opt-in checks against a real AWS account prepared by scripts/seed_cloudwatch_demo.py."""

import asyncio
import os

import pytest

from incidentflow.agent.findings import CloudWatchFinding
from incidentflow.agent.mcp_clients.cloudwatch import CLOUDWATCH_READ_TOOL_NAMES
from incidentflow.agent.tools import cloudwatch_tools
from incidentflow.core.config import get_settings

pytestmark = pytest.mark.skipif(
    os.getenv("INCIDENTFLOW_RUN_AWS_TESTS") != "1",
    reason="Set INCIDENTFLOW_RUN_AWS_TESTS=1 to query the real CloudWatch MCP server.",
)


def test_live_cloudwatch_server_exposes_the_approved_read_tools() -> None:
    get_settings.cache_clear()

    async def discover() -> list[str]:
        async with cloudwatch_tools._create_cloudwatch_mcp_client().open_read_session() as session:
            return list(session.tools)

    assert set(asyncio.run(discover())) == set(CLOUDWATCH_READ_TOOL_NAMES)


def test_live_cloudwatch_investigation_returns_a_structured_finding() -> None:
    get_settings.cache_clear()
    if not get_settings().cloudwatch_mcp_enabled:
        pytest.skip("CLOUDWATCH_MCP_ENABLED must be true for the live investigation test.")

    finding = CloudWatchFinding.model_validate_json(
        asyncio.run(
            cloudwatch_tools.ask_cloudwatch.ainvoke(
                {
                    "incident_context": "payment-service returns HTTP 500 errors.",
                    "service_name": "payment-service",
                }
            )
        )
    )

    assert finding.investigation_status in {"completed", "partial"}
    assert finding.time_window is not None

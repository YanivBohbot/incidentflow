import json

import pytest

from evaluation.harness.fixtures import (
    FINDING_MODELS,
    CallLog,
    fixture_delegations,
    unavailable_finding_json,
)
from incidentflow.agent.orchestration.supervisor import (
    DELEGATION_TOOLS,
    build_investigation_supervisor,
)
from incidentflow.core.config import get_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_fixture_delegations_copy_real_tool_metadata() -> None:
    stubs = {t.name: t for t in fixture_delegations({}, [])}
    assert set(stubs) == {t.name for t in DELEGATION_TOOLS}
    for real in DELEGATION_TOOLS:
        assert stubs[real.name].description == real.description
        assert stubs[real.name].args == real.args


@pytest.mark.anyio
async def test_fixture_delegation_returns_frozen_finding_and_records_call() -> None:
    log: CallLog = []
    stub = {t.name: t for t in fixture_delegations({"ask_knowledge": '{"x": 1}'}, log)}
    assert await stub["ask_knowledge"].ainvoke({"incident_context": "pool"}) == '{"x": 1}'
    assert log == [{"tool": "ask_knowledge", "args": {"incident_context": "pool"}}]


@pytest.mark.anyio
async def test_fixture_delegation_without_finding_returns_unavailable_placeholder() -> None:
    log: CallLog = []
    stub = {t.name: t for t in fixture_delegations({}, log)}
    finding = json.loads(await stub["ask_github"].ainvoke({"incident_context": "c"}))
    assert finding["confidence"] == 0 and "unavailable" in finding["summary"]
    assert log[0]["tool"] == "ask_github"


def test_unavailable_finding_validates_against_every_finding_model() -> None:
    for name, model in FINDING_MODELS.items():
        finding = model.model_validate_json(unavailable_finding_json(name))
        assert finding.confidence == 0
        assert finding.summary.endswith(" is unavailable in this evaluation scenario.")


def test_build_investigation_supervisor_accepts_injected_tools(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        agent = build_investigation_supervisor(tools=fixture_delegations({}, []))
    finally:
        get_settings.cache_clear()
    assert agent is not None

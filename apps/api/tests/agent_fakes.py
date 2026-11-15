"""Test doubles for running a real create_agent without calling OpenAI."""

import json
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from incidentflow.agent.findings import InvestigationReport


class ScriptedChatModel(GenericFakeChatModel):
    """Replays a fixed list of AI messages, so a test scripts the agent's tool choices.

    create_agent binds tools to its model; this model accepts them and keeps its script.
    """

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        return self


def scripted_model(turns: Iterable[list[tuple[str, dict[str, Any]]] | str]) -> ScriptedChatModel:
    """Build a model whose turn N calls the given tools (name, args), or answers with text."""
    messages = []
    for index, turn in enumerate(turns):
        if isinstance(turn, str):
            messages.append(AIMessage(content=turn))
            continue
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": name, "args": args, "id": f"call-{index}-{position}"}
                    for position, (name, args) in enumerate(turn)
                ],
            )
        )
    return ScriptedChatModel(messages=iter(messages))


def as_text(payload: object) -> str:
    return json.dumps(payload)


class ApprovalGatedSupervisor:
    """Act like a Jira specialist that pauses before its write tool can run.

    `calls` counts every supervisor run; `resume_values` records each operator decision the
    paused write received, so a test can tell whether an approved write would run twice.
    """

    def __init__(self, report: InvestigationReport) -> None:
        self.report = report
        self.calls = 0
        self.resume_values: list[object] = []

    async def ainvoke(self, _payload: dict, *, config: dict) -> dict:
        assert config["configurable"]["thread_id"].startswith("investigation:")
        self.calls += 1
        decision = interrupt(
            {
                "action_requests": [
                    {
                        "name": "createJiraIssue",
                        "arguments": {"summary": "Payment API errors"},
                        "description": "Jira issue creation requires operator approval.",
                    }
                ]
            }
        )
        self.resume_values.append(decision)
        return {"structured_response": self.report}

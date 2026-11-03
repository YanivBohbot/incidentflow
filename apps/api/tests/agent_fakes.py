"""Test doubles for running a real create_agent without calling OpenAI."""

import json
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


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

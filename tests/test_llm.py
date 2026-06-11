"""Tests for agent.llm — Groq SDK is fully mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.exceptions import AgentError
from agent.llm import GroqChat, _translate


def _resp_with(tool_calls: list, content: str | None = None) -> object:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {"role": "assistant", "content": content}
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _tc(call_id: str, name: str, arguments: str):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def test_translate_with_tool_calls() -> None:
    resp = _resp_with([_tc("c1", "read_file", '{"path":"a"}')])
    turn = _translate(resp)
    assert turn.tool_calls[0].id == "c1"
    assert turn.tool_calls[0].name == "read_file"
    assert turn.tool_calls[0].arguments == '{"path":"a"}'


def test_translate_no_tool_calls() -> None:
    resp = _resp_with([], content="hello")
    turn = _translate(resp)
    assert turn.tool_calls == ()
    assert turn.content == "hello"


async def test_groqchat_invokes_sdk_and_translates() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_resp_with([_tc("c1", "list_files", "")])
    )
    chat = GroqChat(client, model="m")
    turn = await chat([{"role": "user", "content": "hi"}], (), "default")
    assert turn.tool_calls[0].name == "list_files"
    client.chat.completions.create.assert_awaited_once()


async def test_groqchat_wraps_sdk_errors() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("net"))
    chat = GroqChat(client)
    with pytest.raises(AgentError):
        await chat([], (), "none")

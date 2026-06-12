"""Tests for agent.llm — ChatGroq factory; LangChain is mocked."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent import llm


def test_build_chat_model_binds_tools_with_retry(monkeypatch) -> None:
    retried = MagicMock()
    retried.bind_tools = MagicMock(return_value="bound")
    inst = MagicMock()
    inst.with_retry = MagicMock(return_value=retried)
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(return_value=inst))

    out = llm.build_chat_model(api_key="k", model="m", reasoning_effort="none", timeout_s=5)
    assert out == "bound"
    llm.ChatGroq.assert_called_once_with(model="m", api_key="k", timeout=5, reasoning_effort="none")
    inst.with_retry.assert_called_once()
    retried.bind_tools.assert_called_once()

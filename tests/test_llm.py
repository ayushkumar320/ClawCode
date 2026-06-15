"""Tests for agent.llm — ChatGroq factory; LangChain is mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from groq import RateLimitError

from agent import llm


def _fake_chatgroq_factory():
    """Return a MagicMock standing in for ChatGroq, recording each instance."""
    instances = []

    def factory(**kwargs):
        bound = MagicMock(name=f"bound-{kwargs['model']}")
        bound.model = kwargs["model"]
        bound.ainvoke = AsyncMock(return_value=f"response-{kwargs['model']}")
        inst = MagicMock(name=f"inst-{kwargs['model']}")
        inst.bind_tools = MagicMock(return_value=bound)
        instances.append((kwargs, inst, bound))
        return inst

    return factory, instances


def test_build_chat_model_single_when_no_fallbacks(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    out = llm.build_chat_model(
        api_key="k", model="m", reasoning_effort="none", timeout_s=5, fallback_models=()
    )
    assert out is instances[0][2]
    assert len(instances) == 1
    assert instances[0][0]["max_retries"] == 0
    instances[0][1].bind_tools.assert_called_once()


def test_reasoning_effort_only_sent_to_supported_model(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))
    llm.build_chat_model(
        api_key="k",
        model="qwen/qwen3-32b",
        reasoning_effort="none",
        fallback_models=("llama-3.3-70b-versatile",),
    )
    assert instances[0][0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in instances[1][0]


async def test_build_chat_model_wraps_with_fallbacks(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    out = llm.build_chat_model(
        api_key="k",
        model="primary",
        fallback_models=("fb1", "fb2"),
    )
    # Three ChatGroq builds: primary + two fallbacks
    models_built = [kw["model"] for kw, _, _ in instances]
    assert models_built == ["primary", "fb1", "fb2"]
    assert await out.ainvoke(["message"]) == "response-primary"
    instances[0][2].ainvoke.assert_awaited_once()
    instances[1][2].ainvoke.assert_not_awaited()


async def test_build_chat_model_dedupes_primary_from_fallbacks(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    out = llm.build_chat_model(api_key="k", model="primary", fallback_models=("primary", "fb1"))
    models_built = [kw["model"] for kw, _, _ in instances]
    assert models_built == ["primary", "fb1"]  # duplicate "primary" skipped
    assert await out.ainvoke(["message"]) == "response-primary"


async def test_rate_limit_uses_next_model(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))
    model = llm.build_chat_model(
        api_key="k",
        model="primary",
        fallback_models=("fb1", "fb2"),
    )
    response = MagicMock(status_code=429, headers={})
    instances[0][2].ainvoke.side_effect = RateLimitError(
        "rate limited",
        response=response,
        body={"error": {"message": "limit"}},
    )
    assert await model.ainvoke(["message"]) == "response-fb1"
    instances[0][2].ainvoke.assert_awaited_once()
    instances[1][2].ainvoke.assert_awaited_once()
    instances[2][2].ainvoke.assert_not_awaited()


async def test_last_rate_limit_is_raised(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))
    model = llm.build_chat_model(api_key="k", model="primary", fallback_models=("fb1",))
    response = MagicMock(status_code=429, headers={})
    error = RateLimitError(
        "rate limited",
        response=response,
        body={"error": {"message": "limit"}},
    )
    for _, _, bound in instances:
        bound.ainvoke.side_effect = error
    with pytest.raises(RateLimitError):
        await model.ainvoke(["message"])

"""Tests for agent.llm provider-aware chat model construction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from groq import RateLimitError as GroqRateLimitError
from openai import RateLimitError as OpenAIRateLimitError

from agent import llm


def _fake_factory(name: str):
    """Return a constructor mock that records kwargs and bound runnables."""
    instances = []

    def factory(**kwargs):
        bound = MagicMock(name=f"bound-{name}-{kwargs['model']}")
        bound.model = kwargs["model"]
        bound.ainvoke = AsyncMock(return_value=f"response-{kwargs['model']}")
        inst = MagicMock(name=f"inst-{name}-{kwargs['model']}")
        inst.bind_tools = MagicMock(return_value=bound)
        instances.append((kwargs, inst, bound))
        return inst

    return factory, instances


def test_build_chat_model_single_huggingface(monkeypatch) -> None:
    factory, instances = _fake_factory("openai")
    monkeypatch.setattr(llm, "ChatOpenAI", MagicMock(side_effect=factory))

    out = llm.build_chat_model(
        api_key="hf",
        provider="huggingface",
        model="Qwen/Qwen3-Coder-32B",
        timeout_s=5,
        fallback_models=(),
    )
    assert out is instances[0][2]
    assert len(instances) == 1
    assert instances[0][0]["base_url"] == llm.DEFAULT_HF_BASE_URL
    assert instances[0][0]["max_retries"] == 0
    instances[0][1].bind_tools.assert_called_once()


def test_build_chat_model_single_groq_uses_reasoning_effort(monkeypatch) -> None:
    factory, instances = _fake_factory("groq")
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    llm.build_chat_model(
        api_key="g",
        provider="groq",
        model="qwen/qwen3-32b",
        reasoning_effort="none",
        fallback_models=(),
    )
    assert instances[0][0]["reasoning_effort"] == "none"


def test_build_chat_model_groq_non_qwen_skips_reasoning_effort(monkeypatch) -> None:
    factory, instances = _fake_factory("groq")
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    llm.build_chat_model(
        api_key="g",
        provider="groq",
        model="llama",
        reasoning_effort="none",
        fallback_models=(),
    )
    assert "reasoning_effort" not in instances[0][0]


async def test_huggingface_rate_limit_uses_next_model(monkeypatch) -> None:
    factory, instances = _fake_factory("openai")
    monkeypatch.setattr(llm, "ChatOpenAI", MagicMock(side_effect=factory))
    model = llm.build_chat_model(
        api_key="hf",
        provider="huggingface",
        model="primary",
        fallback_models=("fb1", "fb2"),
    )
    response = MagicMock(request=MagicMock(), status_code=429, headers={})
    instances[0][2].ainvoke.side_effect = OpenAIRateLimitError(
        "rate limited",
        response=response,
        body={},
    )
    assert await model.ainvoke(["message"]) == "response-fb1"
    instances[0][2].ainvoke.assert_awaited_once()
    instances[1][2].ainvoke.assert_awaited_once()
    instances[2][2].ainvoke.assert_not_awaited()


async def test_groq_rate_limit_uses_next_model(monkeypatch) -> None:
    factory, instances = _fake_factory("groq")
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))
    model = llm.build_chat_model(
        api_key="g",
        provider="groq",
        model="primary",
        fallback_models=("fb1",),
    )
    response = MagicMock(status_code=429, headers={})
    instances[0][2].ainvoke.side_effect = GroqRateLimitError(
        "rate limited",
        response=response,
        body={"error": {"message": "limit"}},
    )
    assert await model.ainvoke(["message"]) == "response-fb1"


async def test_last_rate_limit_is_raised(monkeypatch) -> None:
    factory, instances = _fake_factory("openai")
    monkeypatch.setattr(llm, "ChatOpenAI", MagicMock(side_effect=factory))
    model = llm.build_chat_model(
        api_key="hf",
        provider="huggingface",
        model="primary",
        fallback_models=("fb1",),
    )
    response = MagicMock(request=MagicMock(), status_code=429, headers={})
    error = OpenAIRateLimitError("rate limited", response=response, body={})
    for _, _, bound in instances:
        bound.ainvoke.side_effect = error
    with pytest.raises(OpenAIRateLimitError):
        await model.ainvoke(["message"])


def test_unsupported_provider_raises() -> None:
    with pytest.raises(ValueError):
        llm.build_chat_model(api_key="x", provider="bogus", fallback_models=())

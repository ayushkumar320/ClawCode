"""Provider-aware LangChain chat model factory used by the orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from groq import RateLimitError as GroqRateLimitError
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from openai import RateLimitError as OpenAIRateLimitError

from agent.tools import TOOLS

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "huggingface"
DEFAULT_MODEL = "Qwen/Qwen3-Coder-32B"
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "deepseek-ai/DeepSeek-R1-0528",
    "meta-llama/Llama-3.3-70B-Instruct",
)
DEFAULT_TIMEOUT_S = 60
DEFAULT_HF_BASE_URL = "https://router.huggingface.co/v1"


def _build_groq(*, api_key: str, model: str, timeout_s: float, reasoning_effort: str) -> Any:
    """Construct a single tool-bound Groq chat model."""
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "timeout": timeout_s,
        "max_retries": 0,
    }
    if model.startswith("qwen/"):
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatGroq(**kwargs).bind_tools(list(TOOLS))


def _build_huggingface(
    *,
    api_key: str,
    model: str,
    timeout_s: float,
    base_url: str | None,
) -> Any:
    """Construct a single tool-bound Hugging Face router chat model."""
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url or DEFAULT_HF_BASE_URL,
        timeout=timeout_s,
        max_retries=0,
    ).bind_tools(list(TOOLS))


def _build_one(
    *,
    provider: str,
    api_key: str,
    model: str,
    timeout_s: float,
    reasoning_effort: str,
    base_url: str | None,
) -> Any:
    """Construct a single tool-bound chat model for the selected provider."""
    if provider == "groq":
        return _build_groq(
            api_key=api_key,
            model=model,
            timeout_s=timeout_s,
            reasoning_effort=reasoning_effort,
        )
    if provider == "huggingface":
        return _build_huggingface(
            api_key=api_key,
            model=model,
            timeout_s=timeout_s,
            base_url=base_url,
        )
    raise ValueError(f"unsupported llm provider: {provider}")


def _is_rate_limit(provider: str, exc: Exception) -> bool:
    """Return whether an exception represents a provider rate limit."""
    if provider == "groq":
        return isinstance(exc, GroqRateLimitError)
    if provider == "huggingface":
        return isinstance(exc, OpenAIRateLimitError)
    return False


def build_chat_model(
    *,
    api_key: str,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    reasoning_effort: str = "default",
    fallback_models: Sequence[str] = DEFAULT_FALLBACK_MODELS,
    base_url: str | None = None,
) -> Any:
    """Return a tool-bound chat runnable with provider-aware rate-limit fallback."""
    model_names = [model, *(fb for fb in fallback_models if fb and fb != model)]
    models = [
        _build_one(
            provider=provider,
            api_key=api_key,
            model=name,
            timeout_s=timeout_s,
            reasoning_effort=reasoning_effort,
            base_url=base_url,
        )
        for name in model_names
    ]
    if len(models) == 1:
        return models[0]
    logger.info("chat provider=%s chain=%s", provider, model_names)

    async def invoke(messages: Any, config: RunnableConfig) -> Any:
        last_error: Exception | None = None
        for index, candidate in enumerate(models):
            try:
                return await candidate.ainvoke(messages, config=config)
            except Exception as exc:  # noqa: BLE001 - provider SDKs differ
                if not _is_rate_limit(provider, exc):
                    raise
                last_error = exc
                if index == len(models) - 1:
                    raise
                logger.warning(
                    "%s model %s rate limited; switching to %s",
                    provider,
                    model_names[index],
                    model_names[index + 1],
                )
        raise last_error or RuntimeError("no chat models configured")

    return RunnableLambda(invoke)

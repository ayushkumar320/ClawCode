"""LangChain ChatGroq factory used by the orchestrator's ``chat`` node.

LangSmith tracing activates automatically when ``LANGCHAIN_TRACING_V2=true``
and ``LANGCHAIN_API_KEY`` are present in the environment — see
``.env.example`` and ``config.settings``. No code change is required to opt in.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from groq import RateLimitError
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_groq import ChatGroq

from agent.tools import TOOLS

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen/qwen3-32b"
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
)
DEFAULT_TIMEOUT_S = 60


def _build_one(*, api_key: str, model: str, timeout_s: float, reasoning_effort: str) -> Any:
    """Construct a single tool-bound ChatGroq model without same-model retries."""
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "timeout": timeout_s,
        "max_retries": 0,
    }
    if model.startswith("qwen/"):
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatGroq(
        **kwargs,
    ).bind_tools(list(TOOLS))


def build_chat_model(
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    reasoning_effort: str = "default",
    fallback_models: Sequence[str] = DEFAULT_FALLBACK_MODELS,
) -> Any:
    """Return a model chain that immediately falls back on Groq rate limits."""
    model_names = [model, *(fb for fb in fallback_models if fb and fb != model)]
    models = [
        _build_one(
            api_key=api_key,
            model=name,
            timeout_s=timeout_s,
            reasoning_effort=reasoning_effort,
        )
        for name in model_names
    ]
    if len(models) == 1:
        return models[0]
    logger.info("chat model chain=%s", model_names)

    async def invoke(messages: Any, config: RunnableConfig) -> Any:
        last_error: RateLimitError | None = None
        for index, candidate in enumerate(models):
            try:
                return await candidate.ainvoke(messages, config=config)
            except RateLimitError as exc:
                last_error = exc
                if index == len(models) - 1:
                    raise
                logger.warning(
                    "Groq model %s rate limited; switching to %s",
                    model_names[index],
                    model_names[index + 1],
                )
        raise last_error  # pragma: no cover - loop always returns or raises

    return RunnableLambda(invoke)

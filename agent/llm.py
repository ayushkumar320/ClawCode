"""LangChain ChatGroq factory used by the orchestrator's ``chat`` node.

LangSmith tracing activates automatically when ``LANGCHAIN_TRACING_V2=true``
and ``LANGCHAIN_API_KEY`` are present in the environment — see
``.env.example`` and ``config.settings``. No code change is required to opt in.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

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
    """Construct a single ChatGroq instance with retry + tools bound."""
    bound = ChatGroq(
        model=model,
        api_key=api_key,
        timeout=timeout_s,
        reasoning_effort=reasoning_effort,
    ).bind_tools(list(TOOLS))
    return bound.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)


def build_chat_model(
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    reasoning_effort: str = "default",
    fallback_models: Sequence[str] = DEFAULT_FALLBACK_MODELS,
) -> Any:
    """Return primary ChatGroq with tool-bound fallbacks for resilience."""
    primary = _build_one(
        api_key=api_key,
        model=model,
        timeout_s=timeout_s,
        reasoning_effort=reasoning_effort,
    )
    fallbacks = [
        _build_one(
            api_key=api_key,
            model=fb,
            timeout_s=timeout_s,
            reasoning_effort=reasoning_effort,
        )
        for fb in fallback_models
        if fb and fb != model
    ]
    if not fallbacks:
        return primary
    logger.info("chat model %s with fallbacks=%s", model, list(fallback_models))
    return primary.with_fallbacks(fallbacks)

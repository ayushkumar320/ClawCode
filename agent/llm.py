"""LangChain ChatGroq factory used by the orchestrator's ``chat`` node.

LangSmith tracing activates automatically when ``LANGCHAIN_TRACING_V2=true``
and ``LANGCHAIN_API_KEY`` are present in the environment — see
``.env.example`` and ``config.settings``. No code change is required to opt in.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_groq import ChatGroq

from agent.tools import TOOLS

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen/qwen3-32b"
DEFAULT_TIMEOUT_S = 60


def build_chat_model(
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    reasoning_effort: str = "default",
) -> Any:
    """Return a ChatGroq model bound to the agent toolset, ready for the graph."""
    base = ChatGroq(
        model=model,
        api_key=api_key,
        timeout=timeout_s,
        reasoning_effort=reasoning_effort,
    ).with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
    return base.bind_tools(list(TOOLS))

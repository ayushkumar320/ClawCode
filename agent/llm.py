"""Thin async adapter around the Groq SDK; orchestrator depends only on the protocol below.

Kept intentionally small: translate Groq SDK output into the orchestrator's
``AssistantTurn`` shape so the rest of the agent never imports ``groq`` directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from groq import AsyncGroq  # type: ignore[import-not-found]

from agent.exceptions import AgentError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen/qwen3-32b"


@dataclass(frozen=True)
class ToolCall:
    """One tool-call request emitted by the assistant turn."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class AssistantTurn:
    """Single LLM response: free-form content plus any tool calls."""

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    raw_message: dict


class GroqChat:
    """Callable adapter: ``await GroqChat(client)(messages, effort)`` → AssistantTurn."""

    def __init__(self, client: AsyncGroq, *, model: str = DEFAULT_MODEL, timeout_s: float = 60.0):
        """Wrap a configured ``AsyncGroq`` client with a fixed model + timeout."""
        self._client = client
        self._model = model
        self._timeout_s = timeout_s

    async def __call__(
        self,
        messages: list[dict],
        tools: tuple[dict, ...],
        reasoning_effort: str,
    ) -> AssistantTurn:
        """Send a single chat completion and translate the response."""
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=list(tools),
                reasoning_effort=reasoning_effort,
                timeout=self._timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 — SDK error surface is broad
            raise AgentError(f"groq chat failed: {exc}") from exc
        return _translate(resp)


def _translate(resp: object) -> AssistantTurn:
    """Convert a Groq SDK response into an AssistantTurn."""
    choice = resp.choices[0]  # type: ignore[attr-defined]
    msg = choice.message
    calls = tuple(
        ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "")
        for tc in (getattr(msg, "tool_calls", None) or ())
    )
    raw = msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
    return AssistantTurn(content=getattr(msg, "content", None), tool_calls=calls, raw_message=raw)

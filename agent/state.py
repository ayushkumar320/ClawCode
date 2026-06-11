"""Persistent agent state model — JSON-round-trippable via pydantic."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """Snapshot of an in-flight task; checkpointed after every tool result."""

    task_id: str
    repo_slug: str
    user_prompt: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    retries: int = 0
    version: int = 1

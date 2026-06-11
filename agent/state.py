"""Graph state schemas for the LangGraph orchestrator."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    """Mutable state flowing through the StateGraph at runtime."""

    task_id: str
    repo_slug: str
    user_prompt: str
    messages: Annotated[list[AnyMessage], add_messages]
    retries: int
    pr_url: str


class AgentState(BaseModel):
    """Persistent snapshot used by ``agent.checkpoints`` for ``/resume``."""

    task_id: str
    repo_slug: str
    user_prompt: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    retries: int = 0
    version: int = 1

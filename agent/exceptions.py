"""Typed exceptions for the agent package."""

from __future__ import annotations


class AgentError(RuntimeError):
    """Base class for orchestrator / tool / state failures."""


class MaxRetriesExceeded(AgentError):
    """Raised when consecutive failing test runs exceed ``MAX_TEST_RETRIES``."""


class UserRejected(AgentError):
    """Raised when the Telegram operator rejects the proposed change."""


class UnknownTool(AgentError):
    """Raised when the LLM requests a tool that is not registered."""


class ToolArgsError(AgentError):
    """Raised when tool-call arguments fail schema validation."""

"""Typed exceptions for the sandbox package."""

from __future__ import annotations


class SandboxError(RuntimeError):
    """Raised on any E2B sandbox lifecycle or execution failure."""


class SandboxTimeoutError(SandboxError):
    """Raised when a sandbox command exceeds its allotted ``timeout_s``."""

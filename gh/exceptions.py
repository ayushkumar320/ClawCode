"""Typed exceptions for the github package."""

from __future__ import annotations


class RepoError(RuntimeError):
    """Raised on local repo / Git operation failure."""


class ProtectedBranchError(RepoError):
    """Raised when an operation targets a protected branch (e.g. main)."""


class PRError(RuntimeError):
    """Raised on GitHub PR API failure."""

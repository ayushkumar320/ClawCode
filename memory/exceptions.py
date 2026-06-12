"""Typed exception for the memory package."""

from __future__ import annotations


class LessonStoreError(RuntimeError):
    """Raised on any ChromaDB / embedding failure inside the lesson store."""

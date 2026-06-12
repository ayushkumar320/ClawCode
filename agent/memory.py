"""Orchestrator-facing helpers: cap, sanitize, and format lessons for prompts.

Lessons retrieved from the store are *untrusted* — they are LLM-authored on a
prior task and may contain prompt-injection attempts. Everything passing
through here is length-capped, stripped of control characters, and wrapped in
``<lesson>...</lesson>`` tags so the model treats them as quoted context.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

logger = logging.getLogger(__name__)

MAX_LESSON_LEN = 512
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class _StoreLike(Protocol):
    async def add_lesson(self, repo_slug: str, text: str) -> None: ...
    async def top_k(self, repo_slug: str, query: str, *, k: int = 3) -> list[str]: ...


def sanitize_lesson(text: str) -> str:
    """Strip control chars, collapse outer whitespace, truncate to ``MAX_LESSON_LEN``."""
    if not text:
        return ""
    cleaned = _CONTROL_RE.sub("", text).strip()
    if len(cleaned) > MAX_LESSON_LEN:
        cleaned = cleaned[: MAX_LESSON_LEN - 3].rstrip() + "..."
    return cleaned


def format_lessons(lessons: list[str]) -> str:
    """Wrap each lesson in tags inside a ``<lessons>`` block; empty input → ``''``."""
    safe = [sanitize_lesson(item) for item in lessons if item and item.strip()]
    safe = [s for s in safe if s]
    if not safe:
        return ""
    body = "\n".join(f"<lesson>{s}</lesson>" for s in safe)
    return f"<lessons>\n{body}\n</lessons>"


async def recall_block(store: _StoreLike, repo_slug: str, query: str, *, k: int = 3) -> str:
    """Return the top-``k`` lessons for this repo as a prompt-ready ``<lessons>`` block."""
    docs = await store.top_k(repo_slug, query, k=k)
    return format_lessons(docs)


async def remember(store: _StoreLike, repo_slug: str, lesson: str) -> None:
    """Sanitize ``lesson`` and add it under ``repo_slug``; empty/whitespace is skipped."""
    safe = sanitize_lesson(lesson)
    if not safe:
        return
    await store.add_lesson(repo_slug, safe)

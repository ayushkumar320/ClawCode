"""Tests for agent.memory — sanitize, format, recall, remember."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent import memory as mem


def test_sanitize_strips_controls() -> None:
    raw = "good\x00middle\x07end"
    assert mem.sanitize_lesson(raw) == "goodmiddleend"


def test_sanitize_truncates_long() -> None:
    raw = "x" * (mem.MAX_LESSON_LEN + 100)
    out = mem.sanitize_lesson(raw)
    assert len(out) == mem.MAX_LESSON_LEN
    assert out.endswith("...")


def test_sanitize_empty_inputs() -> None:
    assert mem.sanitize_lesson("") == ""
    assert mem.sanitize_lesson("   \n\t  ") == ""


def test_format_lessons_wraps_in_tags() -> None:
    block = mem.format_lessons(["a", "b"])
    assert block.startswith("<lessons>") and block.endswith("</lessons>")
    assert "<lesson>a</lesson>" in block
    assert "<lesson>b</lesson>" in block


def test_format_lessons_empty_returns_empty() -> None:
    assert mem.format_lessons([]) == ""
    assert mem.format_lessons(["", "   "]) == ""


async def test_recall_block_pulls_top_k() -> None:
    store = type("S", (), {})()
    store.top_k = AsyncMock(return_value=["one", "two"])
    block = await mem.recall_block(store, "o/r", "query", k=2)
    store.top_k.assert_awaited_once_with("o/r", "query", k=2)
    assert "<lesson>one</lesson>" in block


async def test_remember_skips_empty() -> None:
    store = type("S", (), {})()
    store.add_lesson = AsyncMock()
    await mem.remember(store, "o/r", "")
    store.add_lesson.assert_not_called()


async def test_remember_sanitizes_then_persists() -> None:
    store = type("S", (), {})()
    store.add_lesson = AsyncMock()
    await mem.remember(store, "o/r", "lesson\x00with-control")
    store.add_lesson.assert_awaited_once_with("o/r", "lessonwith-control")


@pytest.mark.parametrize("bad", ["\x00", "\x01\x02"])
def test_sanitize_only_controls_yields_empty(bad: str) -> None:
    assert mem.sanitize_lesson(bad) == ""

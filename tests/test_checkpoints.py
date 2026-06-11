"""Tests for agent.checkpoints — atomic save / load / clear."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import checkpoints as ckpt
from agent.exceptions import AgentError
from agent.state import AgentState


def _state(task_id: str = "t1") -> AgentState:
    return AgentState(task_id=task_id, repo_slug="o/r", user_prompt="x", retries=1)


def test_path_for_rejects_bad_id(tmp_path: Path) -> None:
    for bad in ("", "../escape", ".hidden", "a/b"):
        with pytest.raises(AgentError):
            ckpt.path_for(tmp_path, bad)


async def test_save_then_load(tmp_path: Path) -> None:
    s = _state()
    await ckpt.save(s, tmp_path)
    loaded = await ckpt.load("t1", tmp_path)
    assert loaded == s


async def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert await ckpt.load("nope", tmp_path) is None


async def test_save_is_atomic_no_partial_file(tmp_path: Path) -> None:
    await ckpt.save(_state(), tmp_path)
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".ckpt-")]
    assert leftovers == []


async def test_clear_removes(tmp_path: Path) -> None:
    await ckpt.save(_state(), tmp_path)
    await ckpt.clear("t1", tmp_path)
    assert await ckpt.load("t1", tmp_path) is None


async def test_clear_missing_is_silent(tmp_path: Path) -> None:
    await ckpt.clear("nope", tmp_path)  # must not raise


async def test_load_corrupt_raises(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(AgentError):
        await ckpt.load("bad", tmp_path)

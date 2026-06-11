"""Tests for agent.tools — schema validation + dispatch (gh + sandbox mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent import tools as agent_tools
from agent.exceptions import ToolArgsError, UnknownTool
from agent.tools import ToolContext


def _ctx(monkeypatch) -> ToolContext:
    """Build a ToolContext and monkeypatch gh + sandbox calls to async stubs."""
    repo = SimpleNamespace(slug="o/r")
    sandbox = SimpleNamespace()
    monkeypatch.setattr(agent_tools.rm, "list_files", AsyncMock(return_value=["a.py"]))
    monkeypatch.setattr(agent_tools.rm, "read_file", AsyncMock(return_value="hi"))
    monkeypatch.setattr(agent_tools.rm, "write_file", AsyncMock())
    monkeypatch.setattr(
        agent_tools.er,
        "run_pytest",
        AsyncMock(
            return_value=SimpleNamespace(exit_code=0, stdout="ok", stderr="", duration_s=0.1)
        ),
    )
    return ToolContext(repo=repo, sandbox=sandbox, e2b_api_key="k")


def test_schemas_cover_all_tools() -> None:
    names = {s["function"]["name"] for s in agent_tools.TOOL_SCHEMAS}
    assert names == {"list_files", "read_file", "write_file", "run_tests", "task_complete"}


async def test_list_files(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    out = await agent_tools.dispatch("list_files", "", ctx)
    assert out == {"files": ["a.py"]}


async def test_read_file_ok(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    out = await agent_tools.dispatch("read_file", '{"path": "a.py"}', ctx)
    assert out == {"content": "hi"}


async def test_read_file_missing_arg(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    with pytest.raises(ToolArgsError):
        await agent_tools.dispatch("read_file", "{}", ctx)


async def test_write_file_ok(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    out = await agent_tools.dispatch("write_file", '{"path": "a.py", "content": "x"}', ctx)
    assert out == {"ok": True}
    agent_tools.rm.write_file.assert_awaited_once()


async def test_run_tests(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    out = await agent_tools.dispatch("run_tests", "", ctx)
    assert out["exit_code"] == 0
    assert out["stdout"] == "ok"


async def test_task_complete(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    out = await agent_tools.dispatch("task_complete", '{"summary": "done", "lesson": "x"}', ctx)
    assert out == {"summary": "done", "lesson": "x"}


async def test_task_complete_lesson_default(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    out = await agent_tools.dispatch("task_complete", '{"summary": "done"}', ctx)
    assert out == {"summary": "done", "lesson": ""}


async def test_unknown_tool(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    with pytest.raises(UnknownTool):
        await agent_tools.dispatch("nope", "{}", ctx)


async def test_malformed_json(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    with pytest.raises(ToolArgsError):
        await agent_tools.dispatch("read_file", "{not json", ctx)


async def test_extra_args_rejected(monkeypatch) -> None:
    ctx = _ctx(monkeypatch)
    with pytest.raises(ToolArgsError):
        await agent_tools.dispatch("read_file", '{"path": "a", "extra": 1}', ctx)

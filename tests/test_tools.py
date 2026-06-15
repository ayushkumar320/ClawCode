"""Tests for agent.tools — LangChain @tool functions; gh + sandbox mocked."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent import tools as agent_tools


def _config(monkeypatch, *, exit_code: int = 0) -> dict:
    """Patch gh + sandbox and return a RunnableConfig wiring them in."""
    repo = SimpleNamespace(slug="o/r", path=SimpleNamespace())
    sandbox = SimpleNamespace()
    monkeypatch.setattr(agent_tools.rm, "list_files", AsyncMock(return_value=["a.py"]))
    monkeypatch.setattr(agent_tools.rm, "read_file", AsyncMock(return_value="hi"))
    monkeypatch.setattr(agent_tools.rm, "write_file", AsyncMock())
    monkeypatch.setattr(agent_tools.er, "upload_repo", AsyncMock(return_value=1))
    monkeypatch.setattr(
        agent_tools.er,
        "install_deps",
        AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="", stderr="", duration_s=0.1)),
    )
    monkeypatch.setattr(
        agent_tools.er,
        "run_pytest",
        AsyncMock(
            return_value=SimpleNamespace(
                exit_code=exit_code, stdout="ok", stderr="", duration_s=0.1
            )
        ),
    )
    return {"configurable": {"repo": repo, "sandbox": sandbox, "e2b_api_key": "k"}}


def test_tools_registered() -> None:
    names = set(agent_tools.TOOLS_BY_NAME)
    assert names == {"list_files", "read_file", "write_file", "run_tests", "task_complete"}


async def test_list_files(monkeypatch) -> None:
    cfg = _config(monkeypatch)
    raw = await agent_tools.list_files.ainvoke({}, config=cfg)
    assert json.loads(raw) == {"files": ["a.py"]}


async def test_read_file_ok(monkeypatch) -> None:
    cfg = _config(monkeypatch)
    raw = await agent_tools.read_file.ainvoke({"path": "a.py"}, config=cfg)
    assert json.loads(raw) == {"content": "hi"}


async def test_write_file_ok(monkeypatch) -> None:
    cfg = _config(monkeypatch)
    raw = await agent_tools.write_file.ainvoke({"path": "a.py", "content": "x"}, config=cfg)
    assert json.loads(raw) == {"ok": True}
    agent_tools.rm.write_file.assert_awaited_once()


async def test_run_tests(monkeypatch) -> None:
    cfg = _config(monkeypatch, exit_code=0)
    raw = await agent_tools.run_tests.ainvoke({}, config=cfg)
    assert json.loads(raw)["exit_code"] == 0
    agent_tools.er.upload_repo.assert_awaited_once()
    agent_tools.er.install_deps.assert_awaited_once()


async def test_task_complete() -> None:
    raw = await agent_tools.task_complete.ainvoke({"summary": "done", "lesson": "x"})
    assert json.loads(raw) == {"summary": "done", "lesson": "x"}


async def test_task_complete_default_lesson() -> None:
    raw = await agent_tools.task_complete.ainvoke({"summary": "done"})
    assert json.loads(raw) == {"summary": "done", "lesson": ""}


async def test_missing_configurable_raises(monkeypatch) -> None:
    with pytest.raises(KeyError):
        await agent_tools.list_files.ainvoke({}, config={"configurable": {}})

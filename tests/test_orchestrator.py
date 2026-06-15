"""Tests for the LangGraph orchestrator — ChatGroq + gh + sandbox all mocked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from agent import checkpoints
from agent import orchestrator as orch
from agent import tools as agent_tools
from agent.exceptions import MaxRetriesExceeded, UserRejected


class _FakeChat:
    """Deterministic stand-in for the bound ChatGroq runnable used in the graph."""

    def __init__(self, scripted: list[AIMessage]):
        self._scripted = list(scripted)

    async def ainvoke(self, messages, config=None):
        if not self._scripted:
            raise AssertionError("FakeChat exhausted")
        return self._scripted.pop(0)


def _ai(tool_calls: list[dict] | None = None, content: str = "") -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _patch_chat(monkeypatch, scripted: list[AIMessage]) -> _FakeChat:
    fake = _FakeChat(scripted)
    monkeypatch.setattr(orch, "build_chat_model", lambda **_: fake)
    return fake


def _patch_tools(monkeypatch, *, exit_code: int = 0) -> None:
    """Mock the gh + sandbox functions our @tool functions delegate to."""
    monkeypatch.setattr(agent_tools.rm, "list_files", AsyncMock(return_value=["a.py"]))
    monkeypatch.setattr(agent_tools.rm, "read_file", AsyncMock(return_value="hi"))
    monkeypatch.setattr(agent_tools.rm, "write_file", AsyncMock())
    monkeypatch.setattr(agent_tools.er, "upload_repo", AsyncMock(return_value=1))
    monkeypatch.setattr(agent_tools.er, "install_deps", AsyncMock())
    monkeypatch.setattr(
        agent_tools.er,
        "run_pytest",
        AsyncMock(
            return_value=SimpleNamespace(exit_code=exit_code, stdout="", stderr="", duration_s=0.0)
        ),
    )


def _deps(*, approval_ok: bool = True) -> orch.OrchestratorDeps:
    repo = SimpleNamespace(slug="o/r", path=Path("/tmp/repo"))
    sandbox = SimpleNamespace()
    return orch.OrchestratorDeps(
        setup=AsyncMock(return_value=(repo, sandbox)),
        teardown=AsyncMock(),
        publish=AsyncMock(return_value="https://gh/pr/1"),
        approval=AsyncMock(return_value=approval_ok),
        groq_api_key="g",
        e2b_api_key="k",
        max_retries=2,
    )


# ---------- pure helpers ----------


def test_classify_effort_short_single() -> None:
    assert orch.classify_effort("add a function to utils.py") == "none"


def test_classify_effort_default_for_long() -> None:
    assert orch.classify_effort(" ".join(["word"] * 50)) == "default"


def test_build_initial_messages_shape() -> None:
    msgs = orch.build_initial_messages("o/r", "do thing")
    assert len(msgs) == 2
    assert "o/r" in msgs[1].content


def test_trace_tags_include_task_and_repo() -> None:
    tags = orch._trace_tags("t1", "o/r")
    assert "task:t1" in tags and "repo:o/r" in tags


# ---------- graph end-to-end ----------


async def test_run_task_happy_path(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch, exit_code=0)
    _patch_chat(
        monkeypatch,
        [
            _ai([{"id": "c1", "name": "list_files", "args": {}}]),
            _ai([{"id": "c2", "name": "run_tests", "args": {}}]),
            _ai([{"id": "c3", "name": "task_complete", "args": {"summary": "done"}}]),
        ],
    )
    deps = _deps()
    url = await orch.run_task("t1", "o/r", "add x", deps)
    assert url == "https://gh/pr/1"
    deps.approval.assert_awaited_once()
    deps.publish.assert_awaited_once()
    deps.teardown.assert_awaited_once()


async def test_run_task_max_retries_aborts(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch, exit_code=1)
    _patch_chat(
        monkeypatch,
        [_ai([{"id": f"c{i}", "name": "run_tests", "args": {}}]) for i in range(10)],
    )
    deps = _deps()
    deps.max_retries = 2
    with pytest.raises(MaxRetriesExceeded):
        await orch.run_task("t-abort", "o/r", "add x", deps)
    deps.teardown.assert_awaited_once()


async def test_run_task_user_rejection(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    _patch_chat(
        monkeypatch,
        [
            _ai([{"id": "c1", "name": "run_tests", "args": {}}]),
            _ai([{"id": "c2", "name": "task_complete", "args": {"summary": "x"}}]),
        ],
    )
    deps = _deps(approval_ok=False)
    with pytest.raises(UserRejected):
        await orch.run_task("t-rej", "o/r", "add x", deps)
    deps.publish.assert_not_awaited()
    deps.teardown.assert_awaited_once()


async def test_run_task_recalls_and_saves_lessons(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    _patch_chat(
        monkeypatch,
        [
            _ai([{"id": "c0", "name": "run_tests", "args": {}}]),
            _ai(
                [
                    {
                        "id": "c1",
                        "name": "task_complete",
                        "args": {"summary": "ok", "lesson": "lesson body"},
                    }
                ]
            ),
        ],
    )
    deps = _deps()
    recall = AsyncMock(return_value="<lessons>\n<lesson>prior</lesson>\n</lessons>")
    save = AsyncMock()
    deps.recall_lessons = recall
    deps.save_lesson = save
    url = await orch.run_task("t-mem", "o/r", "add x", deps)
    assert url == "https://gh/pr/1"
    recall.assert_awaited_once_with("o/r", "add x")
    save.assert_awaited_once_with("o/r", "lesson body")


def test_build_initial_messages_includes_lessons() -> None:
    msgs = orch.build_initial_messages("o/r", "do thing", "<lessons>x</lessons>")
    assert len(msgs) == 3
    assert "lessons" in msgs[1].content


async def test_run_task_nudges_on_empty_turn(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    _patch_chat(
        monkeypatch,
        [
            _ai(content="thinking..."),
            _ai([{"id": "c1", "name": "run_tests", "args": {}}]),
            _ai([{"id": "c2", "name": "task_complete", "args": {"summary": "ok"}}]),
        ],
    )
    deps = _deps()
    url = await orch.run_task("t-nudge", "o/r", "add x", deps)
    assert url == "https://gh/pr/1"


async def test_run_task_resumes_from_checkpoint(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    _patch_chat(
        monkeypatch,
        [_ai([{"id": "c1", "name": "list_files", "args": {}}])],
    )
    deps = _deps()
    deps.checkpoint_dir = tmp_path
    with pytest.raises(AssertionError, match="exhausted"):
        await orch.run_task("t-resume", "o/r", "add x", deps)
    saved = await checkpoints.load("t-resume", tmp_path)
    assert saved is not None
    assert saved.messages

    _patch_chat(
        monkeypatch,
        [
            _ai([{"id": "c2", "name": "run_tests", "args": {}}]),
            _ai([{"id": "c3", "name": "task_complete", "args": {"summary": "done"}}]),
        ],
    )
    url = await orch.run_task("t-resume", "ignored/repo", "ignored prompt", deps)
    assert url == "https://gh/pr/1"
    assert await checkpoints.load("t-resume", tmp_path) is None


async def test_task_complete_requires_green_tests(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    _patch_chat(
        monkeypatch,
        [
            _ai([{"id": "c1", "name": "task_complete", "args": {"summary": "early"}}]),
            _ai([{"id": "c2", "name": "run_tests", "args": {}}]),
            _ai([{"id": "c3", "name": "task_complete", "args": {"summary": "done"}}]),
        ],
    )
    deps = _deps()
    url = await orch.run_task("t-guard", "o/r", "add x", deps)
    assert url == "https://gh/pr/1"
    deps.publish.assert_awaited_once()

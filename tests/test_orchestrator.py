"""Tests for agent.orchestrator — Groq, gh, sandbox all mocked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent import orchestrator as orch
from agent.exceptions import MaxRetriesExceeded, UserRejected
from agent.llm import AssistantTurn, ToolCall

# ---------- helpers ----------


def _turn(*calls: tuple[str, str, str], content: str | None = None) -> AssistantTurn:
    """Build an AssistantTurn from (id, name, args) triples."""
    tcs = tuple(ToolCall(id=cid, name=name, arguments=args) for cid, name, args in calls)
    return AssistantTurn(content=content, tool_calls=tcs, raw_message={"role": "assistant"})


def _deps(tmp_path: Path, chat: AsyncMock, *, approval_ok: bool = True) -> orch.OrchestratorDeps:
    """Build OrchestratorDeps with stub setup/teardown/publish/approval."""
    repo = SimpleNamespace(slug="o/r")
    sandbox = SimpleNamespace()
    return orch.OrchestratorDeps(
        chat=chat,
        setup=AsyncMock(return_value=(repo, sandbox)),
        teardown=AsyncMock(),
        publish=AsyncMock(return_value="https://gh/pr/1"),
        approval=AsyncMock(return_value=approval_ok),
        checkpoint_dir=tmp_path,
        e2b_api_key="k",
        max_retries=3,
    )


def _patch_tools(monkeypatch, *, exit_code: int = 0) -> None:
    """Make tool dispatch return canned results without touching gh/sandbox."""

    async def fake_dispatch(name, raw, ctx):
        if name == "list_files":
            return {"files": ["a.py"]}
        if name == "read_file":
            return {"content": "hi"}
        if name == "write_file":
            return {"ok": True}
        if name == "run_tests":
            return {"exit_code": exit_code, "stdout": "", "stderr": ""}
        if name == "task_complete":
            return {"summary": "done", "lesson": "lsn"}
        raise AssertionError(name)

    monkeypatch.setattr(orch.agent_tools, "dispatch", fake_dispatch)


# ---------- classify_effort + initial messages ----------


def test_classify_effort_short_single() -> None:
    assert orch.classify_effort("add a function to utils.py") == "none"


def test_classify_effort_default_for_long() -> None:
    long = " ".join(["word"] * 50)
    assert orch.classify_effort(long) == "default"


def test_build_initial_messages_shape() -> None:
    msgs = orch.build_initial_messages("o/r", "do thing")
    assert msgs[0]["role"] == "system"
    assert "o/r" in msgs[1]["content"]


# ---------- run_task: happy path ----------


async def test_run_task_happy_path(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch, exit_code=0)
    chat = AsyncMock(
        side_effect=[
            _turn(("c1", "list_files", "")),
            _turn(("c2", "run_tests", "")),
            _turn(("c3", "task_complete", '{"summary": "done"}')),
        ]
    )
    deps = _deps(tmp_path, chat)
    url = await orch.run_task("t1", "o/r", "add x", deps)
    assert url == "https://gh/pr/1"
    deps.approval.assert_awaited_once()
    deps.publish.assert_awaited_once()
    deps.teardown.assert_awaited_once()
    # checkpoint cleared after success
    assert not (tmp_path / "t1.json").exists()


# ---------- no tool call → nudge then continue ----------


async def test_run_task_nudges_on_empty_turn(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    chat = AsyncMock(
        side_effect=[
            _turn(content="thinking..."),
            _turn(("c1", "task_complete", '{"summary": "ok"}')),
        ]
    )
    deps = _deps(tmp_path, chat)
    await orch.run_task("t2", "o/r", "add x", deps)
    assert chat.await_count == 2


# ---------- retries ----------


async def test_run_task_max_retries_aborts(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch, exit_code=1)
    chat = AsyncMock(side_effect=[_turn(("c1", "run_tests", "")) for _ in range(10)])
    deps = _deps(tmp_path, chat)
    deps.max_retries = 2
    with pytest.raises(MaxRetriesExceeded):
        await orch.run_task("t3", "o/r", "add x", deps)
    deps.teardown.assert_awaited_once()


async def test_run_task_resets_retries_on_green(tmp_path: Path, monkeypatch) -> None:
    results = iter([1, 1, 0])

    async def fake_dispatch(name, raw, ctx):
        if name == "run_tests":
            return {"exit_code": next(results), "stdout": "", "stderr": ""}
        if name == "task_complete":
            return {"summary": "ok"}
        return {}

    monkeypatch.setattr(orch.agent_tools, "dispatch", fake_dispatch)
    chat = AsyncMock(
        side_effect=[
            _turn(("c1", "run_tests", "")),
            _turn(("c2", "run_tests", "")),
            _turn(("c3", "run_tests", "")),
            _turn(("c4", "task_complete", '{"summary": "ok"}')),
        ]
    )
    deps = _deps(tmp_path, chat)
    deps.max_retries = 3
    url = await orch.run_task("t4", "o/r", "add x", deps)
    assert url == "https://gh/pr/1"


# ---------- user rejection ----------


async def test_run_task_rejection_raises(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    chat = AsyncMock(side_effect=[_turn(("c1", "task_complete", '{"summary": "x"}'))])
    deps = _deps(tmp_path, chat, approval_ok=False)
    with pytest.raises(UserRejected):
        await orch.run_task("t5", "o/r", "add x", deps)
    deps.publish.assert_not_awaited()
    deps.teardown.assert_awaited_once()


# ---------- checkpoint resume ----------


async def test_run_task_resumes_from_checkpoint(tmp_path: Path, monkeypatch) -> None:
    _patch_tools(monkeypatch)
    from agent import checkpoints as ckpt
    from agent.state import AgentState

    seed = AgentState(
        task_id="t6",
        repo_slug="o/r",
        user_prompt="add x",
        messages=[{"role": "system", "content": "prior"}],
        retries=0,
    )
    await ckpt.save(seed, tmp_path)
    chat = AsyncMock(side_effect=[_turn(("c1", "task_complete", '{"summary": "ok"}'))])
    deps = _deps(tmp_path, chat)
    await orch.run_task("t6", "o/r", "add x", deps)
    # first call should have used the prior messages list, not a fresh one
    first_messages = chat.await_args_list[0].args[0]
    assert any(m.get("content") == "prior" for m in first_messages)

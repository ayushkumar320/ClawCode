"""Tests for agent.wiring — every downstream client is mocked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from agent import wiring
from config.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        groq_api_key="g",
        telegram_bot_token="t",
        telegram_allowed_user_ids=(1,),
        github_token="gh",
        github_default_branch="main",
        e2b_api_key="e",
        log_level="INFO",
        checkpoint_dir=tmp_path / "ckpt",
        chroma_dir=tmp_path / "chroma",
        max_test_retries=3,
    )


async def test_make_setup_clones_starts_uploads_installs(monkeypatch, tmp_path: Path) -> None:
    handle = SimpleNamespace(slug="o/r", path=tmp_path / "repo")
    sandbox = SimpleNamespace()
    monkeypatch.setattr(wiring.repo_manager, "clone_repo", AsyncMock(return_value=handle))
    from sandbox import e2b_runner

    monkeypatch.setattr(e2b_runner, "start_sandbox", AsyncMock(return_value=sandbox))
    monkeypatch.setattr(e2b_runner, "upload_repo", AsyncMock(return_value=1))
    monkeypatch.setattr(e2b_runner, "install_deps", AsyncMock())

    setup = wiring.make_setup("gh", "main", "e2b-key")
    repo, sb = await setup("task-1", "o/r")
    assert repo is handle
    assert sb is sandbox
    e2b_runner.start_sandbox.assert_awaited_once_with("e2b-key")
    e2b_runner.upload_repo.assert_awaited_once()
    e2b_runner.install_deps.assert_awaited_once()


async def test_make_teardown_shuts_down(monkeypatch) -> None:
    from sandbox import e2b_runner

    monkeypatch.setattr(e2b_runner, "shutdown", AsyncMock())
    teardown = wiring.make_teardown()
    await teardown("sb-handle")
    e2b_runner.shutdown.assert_awaited_once_with("sb-handle")


async def test_make_publish_orchestrates_branch_commit_push_pr(monkeypatch) -> None:
    monkeypatch.setattr(wiring.repo_manager, "create_branch", AsyncMock())
    monkeypatch.setattr(wiring.repo_manager, "commit", AsyncMock(return_value="sha"))
    monkeypatch.setattr(wiring.repo_manager, "push_branch", AsyncMock())
    monkeypatch.setattr(wiring.pr_manager, "open_pr", AsyncMock(return_value="https://gh/pr/1"))

    publish = wiring.make_publish("tkn")
    repo = SimpleNamespace(slug="o/r", default_branch="main")
    url = await publish(repo, "agent/x", "title", "body")
    assert url == "https://gh/pr/1"
    wiring.repo_manager.create_branch.assert_awaited_once_with(repo, "agent/x")
    wiring.repo_manager.commit.assert_awaited_once()
    wiring.repo_manager.push_branch.assert_awaited_once_with(repo, "agent/x", token="tkn")
    wiring.pr_manager.open_pr.assert_awaited_once()


async def test_make_lessons_recall_and_save(monkeypatch, tmp_path: Path) -> None:
    fake_store = MagicMock()
    monkeypatch.setattr(wiring, "LessonStore", MagicMock(return_value=fake_store))
    monkeypatch.setattr(wiring.agent_memory, "recall_block", AsyncMock(return_value="<lessons/>"))
    monkeypatch.setattr(wiring.agent_memory, "remember", AsyncMock())

    recall, save = wiring.make_lessons(tmp_path)
    assert await recall("o/r", "q") == "<lessons/>"
    await save("o/r", "lsn")
    wiring.agent_memory.recall_block.assert_awaited_once()
    wiring.agent_memory.remember.assert_awaited_once_with(fake_store, "o/r", "lsn")


def test_compose_deps_populates_every_field(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wiring, "LessonStore", MagicMock())
    deps = wiring.compose_deps(_settings(tmp_path), approval=AsyncMock())
    assert deps.setup is not None
    assert deps.teardown is not None
    assert deps.publish is not None
    assert deps.approval is not None
    assert deps.recall_lessons is not None
    assert deps.save_lesson is not None
    assert deps.groq_api_key == "g"
    assert deps.e2b_api_key == "e"
    assert deps.max_retries == 3


def test_cleanup_workdir_idempotent(tmp_path: Path) -> None:
    wiring.cleanup_workdir(tmp_path / "does-not-exist")  # must not raise

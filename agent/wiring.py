"""Compose ``OrchestratorDeps`` from real gh / sandbox / memory clients.

Lives under ``agent/`` because it crosses every other package; per rule §8 the
``agent/`` boundary may depend on ``gh/``, ``sandbox/``, and ``memory/``.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agent import memory as agent_memory
from agent.orchestrator import OrchestratorDeps
from config.settings import Settings
from gh import pr_manager, repo_manager
from memory.store import LessonStore

# Sandbox is imported lazily inside helpers so the e2b SDK isn't required for
# wiring unit tests that mock these functions out.

logger = logging.getLogger(__name__)


def make_setup(
    token: str,
    default_branch: str,
    e2b_api_key: str,
    workdirs: dict[int, Path] | None = None,
) -> Callable:
    """Build the per-task ``setup`` callable: clone repo, start sandbox, upload, install deps."""
    from sandbox import e2b_runner

    async def setup(task_id: str, repo_slug: str) -> tuple[Any, Any]:
        workdir = Path(tempfile.mkdtemp(prefix=f"clawcode-{task_id}-"))
        try:
            repo = await repo_manager.clone_repo(
                repo_slug,
                workdir / "repo",
                token=token,
                default_branch=default_branch,
            )
            sandbox = await e2b_runner.start_sandbox(e2b_api_key)
            await e2b_runner.upload_repo(sandbox, repo.path)
            await e2b_runner.install_deps(sandbox, api_key=e2b_api_key)
        except Exception:
            cleanup_workdir(workdir)
            raise
        if workdirs is not None:
            workdirs[id(sandbox)] = workdir
        return repo, sandbox

    return setup


def make_teardown(workdirs: dict[int, Path] | None = None) -> Callable:
    """Build the ``teardown`` callable: stop sandbox and remove its temp clone."""
    from sandbox import e2b_runner

    async def teardown(sandbox: Any) -> None:
        try:
            await e2b_runner.shutdown(sandbox)
        finally:
            workdir = workdirs.pop(id(sandbox), None) if workdirs is not None else None
            if workdir is not None:
                cleanup_workdir(workdir)

    return teardown


def make_publish(token: str) -> Callable:
    """Build the ``publish`` callable: branch + commit + push + idempotent PR."""

    async def publish(repo, branch: str, title: str, body: str) -> str:
        await repo_manager.create_branch(repo, branch)
        await repo_manager.commit(repo, title)
        await repo_manager.push_branch(repo, branch, token=token)
        return await pr_manager.open_pr(
            repo.slug,
            head=branch,
            base=repo.default_branch,
            title=title,
            body=body,
            token=token,
        )

    return publish


def make_lessons(chroma_dir: Path) -> tuple[Callable, Callable]:
    """Return ``(recall, save)`` callables sharing a single ``LessonStore`` instance."""
    store = LessonStore(chroma_dir)

    async def recall(repo_slug: str, query: str) -> str:
        return await agent_memory.recall_block(store, repo_slug, query, k=3)

    async def save(repo_slug: str, lesson: str) -> None:
        await agent_memory.remember(store, repo_slug, lesson)

    return recall, save


def compose_deps(
    settings: Settings,
    approval: Callable[[str, str], Awaitable[bool]],
) -> OrchestratorDeps:
    """Build a fully-wired ``OrchestratorDeps`` for a real (non-test) task run."""
    recall, save = make_lessons(settings.chroma_dir)
    workdirs: dict[int, Path] = {}
    return OrchestratorDeps(
        setup=make_setup(
            settings.github_token,
            settings.github_default_branch,
            settings.e2b_api_key,
            workdirs,
        ),
        teardown=make_teardown(workdirs),
        publish=make_publish(settings.github_token),
        approval=approval,
        groq_api_key=settings.groq_api_key,
        e2b_api_key=settings.e2b_api_key,
        max_retries=settings.max_test_retries,
        model=settings.groq_model,
        fallback_models=settings.groq_fallback_models,
        recall_lessons=recall,
        save_lesson=save,
        checkpoint_dir=settings.checkpoint_dir,
    )


def cleanup_workdir(path: Path) -> None:
    """Best-effort recursive delete of a temp clone directory; swallow errors."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError as exc:  # pragma: no cover — rmtree(ignore_errors) already swallows
        logger.warning("workdir cleanup failed: %s: %s", path, exc)

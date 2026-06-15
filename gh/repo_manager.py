"""Local Git operations against a cloned GitHub repository.

All GitPython calls are synchronous; we wrap them with ``asyncio.to_thread``
so they remain non-blocking inside the bot's event loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from git import GitCommandError, Repo
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from gh.exceptions import ProtectedBranchError, RepoError

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PROTECTED_DEFAULT = frozenset({"main", "master"})


@dataclass(frozen=True)
class RepoHandle:
    """Handle to a working clone on disk."""

    slug: str
    path: Path
    default_branch: str
    protected: frozenset[str] = field(default=_PROTECTED_DEFAULT)


def _scrub(msg: str, token: str | None) -> str:
    """Remove a token (if any) from a message before logging or re-raising."""
    return msg.replace(token, "***") if token else msg


def _remote_url(slug: str, token: str | None) -> str:
    """Build an https remote URL, embedding the token when provided."""
    if not _SLUG_RE.match(slug):
        raise RepoError(f"invalid slug: {slug!r}")
    if token:
        return f"https://x-access-token:{token}@github.com/{slug}.git"
    return f"https://github.com/{slug}.git"


async def clone_repo(
    slug: str,
    dest: Path,
    *,
    token: str | None,
    default_branch: str = "main",
    origin_url: str | None = None,
) -> RepoHandle:
    """Clone ``slug`` into ``dest``. ``origin_url`` overrides for tests."""
    url = origin_url or _remote_url(slug, token)
    try:
        await asyncio.to_thread(Repo.clone_from, url, str(dest))
    except GitCommandError as exc:
        raise RepoError(_scrub(f"clone failed for {slug}: {exc}", token)) from exc
    repo = Repo(str(dest))
    detected_branch = repo.active_branch.name
    selected_branch = default_branch if default_branch in repo.heads else detected_branch
    if selected_branch != default_branch:
        logger.warning(
            "configured default branch %s absent for %s; using %s",
            default_branch,
            slug,
            selected_branch,
        )
    logger.info("cloned %s into %s", slug, dest)
    protected = frozenset(_PROTECTED_DEFAULT | {selected_branch})
    return RepoHandle(
        slug=slug,
        path=dest,
        default_branch=selected_branch,
        protected=protected,
    )


async def list_files(handle: RepoHandle) -> list[str]:
    """Return tracked file paths (relative, posix-style), sorted."""

    def _ls() -> list[str]:
        repo = Repo(str(handle.path))
        out = repo.git.ls_files().splitlines()
        return sorted(p for p in out if p)

    return await asyncio.to_thread(_ls)


async def read_file(handle: RepoHandle, rel_path: str) -> str:
    """Read a UTF-8 file relative to the repo root."""
    target = (handle.path / rel_path).resolve()
    if not _is_within(target, handle.path):
        raise RepoError(f"path escapes repo: {rel_path!r}")
    try:
        return await asyncio.to_thread(target.read_text, encoding="utf-8")
    except OSError as exc:
        raise RepoError(f"read failed: {rel_path}: {exc}") from exc


async def write_file(handle: RepoHandle, rel_path: str, content: str) -> None:
    """Write a UTF-8 file relative to the repo root, creating parents."""
    target = (handle.path / rel_path).resolve()
    if not _is_within(target, handle.path):
        raise RepoError(f"path escapes repo: {rel_path!r}")

    def _write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    await asyncio.to_thread(_write)


def _is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` is inside ``parent`` after resolution."""
    try:
        child.relative_to(parent.resolve())
    except ValueError:
        return False
    return True


async def create_branch(handle: RepoHandle, name: str) -> None:
    """Create and check out a new branch; reject protected names."""
    if not name or "/" in name and name.startswith("/"):
        raise RepoError(f"invalid branch name: {name!r}")
    if name in handle.protected:
        raise ProtectedBranchError(f"refusing to create protected branch: {name}")

    def _create() -> None:
        repo = Repo(str(handle.path))
        repo.git.checkout("-b", name)

    try:
        await asyncio.to_thread(_create)
    except GitCommandError as exc:
        raise RepoError(f"create_branch failed: {name}: {exc}") from exc


async def commit(
    handle: RepoHandle,
    message: str,
    *,
    author_name: str = "ClawCode Agent",
    author_email: str = "agent@clawcode.local",
) -> str:
    """Stage all changes and create a commit. Returns the new commit SHA."""

    def _commit() -> str:
        repo = Repo(str(handle.path))
        repo.git.add(A=True)
        repo.index.commit(
            message,
            author=_actor(author_name, author_email),
            committer=_actor(author_name, author_email),
        )
        return repo.head.commit.hexsha

    try:
        return await asyncio.to_thread(_commit)
    except GitCommandError as exc:
        raise RepoError(f"commit failed: {exc}") from exc


def _actor(name: str, email: str):  # noqa: ANN202 — Actor type leaks GitPython internals
    """Build a GitPython Actor for author/committer."""
    from git import Actor

    return Actor(name, email)


def _is_transient_repo_error(exc: BaseException) -> bool:
    """Retry only on generic RepoError; never on permanent guard violations."""
    return isinstance(exc, RepoError) and not isinstance(exc, ProtectedBranchError)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=1),
    retry=retry_if_exception(_is_transient_repo_error),
    reraise=True,
)
async def push_branch(handle: RepoHandle, name: str, *, token: str | None = None) -> None:
    """Push the given branch to origin; reject protected names."""
    if name in handle.protected:
        raise ProtectedBranchError(f"refusing to push protected branch: {name}")

    def _push() -> None:
        repo = Repo(str(handle.path))
        target = _remote_url(handle.slug, token) if token else "origin"
        repo.git.push(target, f"{name}:{name}")

    try:
        await asyncio.to_thread(_push)
    except GitCommandError as exc:
        message = _scrub(f"push failed for {name}: {exc}", token)
        if "403" in message or "Permission to" in message:
            message += (
                ". Check that GITHUB_TOKEN can access this repository and has "
                "'Contents: Read and write' permission."
            )
        raise RepoError(message) from exc
    logger.info("pushed branch %s for %s", name, handle.slug)

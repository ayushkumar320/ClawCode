"""Tests for gh.repo_manager against a local bare-repo origin (no network)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from git import Repo

from gh import repo_manager as rm
from gh.exceptions import ProtectedBranchError, RepoError


@pytest.fixture()
def origin(tmp_path: Path) -> Path:
    """Create a bare upstream repo with one commit on 'main' and return its path."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(seed),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True)
    return bare


async def _clone(origin: Path, tmp_path: Path) -> rm.RepoHandle:
    return await rm.clone_repo(
        "o/r",
        tmp_path / "work",
        token=None,
        default_branch="main",
        origin_url=str(origin),
    )


def test_remote_url_with_token() -> None:
    url = rm._remote_url("foo/bar", "tkn")
    assert url == "https://x-access-token:tkn@github.com/foo/bar.git"


def test_remote_url_without_token() -> None:
    assert rm._remote_url("foo/bar", None) == "https://github.com/foo/bar.git"


def test_remote_url_bad_slug() -> None:
    with pytest.raises(RepoError):
        rm._remote_url("not a slug", None)


def test_scrub_removes_token() -> None:
    assert "tkn" not in rm._scrub("oops tkn here", "tkn")
    assert rm._scrub("plain", None) == "plain"


async def test_clone_list_read(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    assert h.slug == "o/r"
    assert h.default_branch == "main"
    assert "main" in h.protected
    files = await rm.list_files(h)
    assert files == ["README.md"]
    assert (await rm.read_file(h, "README.md")).strip() == "hello"


async def test_write_then_commit(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    await rm.create_branch(h, "agent/test")
    await rm.write_file(h, "HELLO.md", "hi\n")
    sha = await rm.commit(h, "add hello")
    assert len(sha) == 40
    assert "HELLO.md" in await rm.list_files(h)


async def test_create_branch_rejects_protected(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    with pytest.raises(ProtectedBranchError):
        await rm.create_branch(h, "main")
    with pytest.raises(ProtectedBranchError):
        await rm.create_branch(h, "master")


async def test_push_rejects_protected(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    with pytest.raises(ProtectedBranchError):
        await rm.push_branch(h, "main")


async def test_push_branch_lands(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    await rm.create_branch(h, "agent/test")
    await rm.write_file(h, "HELLO.md", "hi\n")
    await rm.commit(h, "add hello")
    await rm.push_branch(h, "agent/test")
    bare = Repo(str(origin))
    assert "agent/test" in [r.name for r in bare.references]


async def test_read_file_escape_rejected(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    with pytest.raises(RepoError):
        await rm.read_file(h, "../escape.txt")


async def test_write_file_escape_rejected(tmp_path: Path, origin: Path) -> None:
    h = await _clone(origin, tmp_path)
    with pytest.raises(RepoError):
        await rm.write_file(h, "../escape.txt", "nope")


async def test_clone_bad_url_raises(tmp_path: Path) -> None:
    with pytest.raises(RepoError):
        await rm.clone_repo(
            "o/r",
            tmp_path / "x",
            token=None,
            origin_url=str(tmp_path / "does-not-exist"),
        )


async def test_clone_detects_nonstandard_default_branch(tmp_path: Path) -> None:
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "-b", "trunk", str(bare)], check=True)
    subprocess.run(["git", "init", "-b", "trunk", str(seed)], check=True)
    (seed / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(seed),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "trunk"], check=True)
    handle = await rm.clone_repo(
        "o/r",
        tmp_path / "work",
        token=None,
        default_branch="main",
        origin_url=str(bare),
    )
    assert handle.default_branch == "trunk"
    assert "trunk" in handle.protected

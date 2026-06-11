"""Tests for gh.pr_manager — PyGithub is mocked; no network."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gh import pr_manager as pm
from gh.exceptions import PRError


def _fake_github(monkeypatch, repo_mock: MagicMock) -> MagicMock:
    """Patch pm.Github so it returns a stub client whose get_repo yields repo_mock."""
    client = MagicMock()
    client.get_repo.return_value = repo_mock
    monkeypatch.setattr(pm, "Github", lambda token: client)
    return client


def test_qualified_head_unqualified() -> None:
    assert pm._qualified_head("acme/widget", "feat") == "acme:feat"


def test_qualified_head_already_qualified() -> None:
    assert pm._qualified_head("acme/widget", "fork:feat") == "fork:feat"


async def test_open_pr_creates_when_none_exists(monkeypatch) -> None:
    repo = MagicMock()
    repo.get_pulls.return_value = []
    repo.create_pull.return_value = SimpleNamespace(html_url="https://gh/pr/1")
    _fake_github(monkeypatch, repo)

    url = await pm.open_pr(
        "acme/widget",
        head="agent/x",
        base="main",
        title="t",
        body="b",
        token="tkn",
    )
    assert url == "https://gh/pr/1"
    repo.create_pull.assert_called_once_with(title="t", body="b", head="agent/x", base="main")


async def test_open_pr_idempotent(monkeypatch) -> None:
    existing = SimpleNamespace(html_url="https://gh/pr/42")
    repo = MagicMock()
    repo.get_pulls.return_value = [existing]
    _fake_github(monkeypatch, repo)

    url = await pm.open_pr(
        "acme/widget",
        head="agent/x",
        base="main",
        title="t",
        body="b",
        token="tkn",
    )
    assert url == "https://gh/pr/42"
    repo.create_pull.assert_not_called()


async def test_open_pr_missing_token() -> None:
    with pytest.raises(PRError):
        await pm.open_pr("a/b", head="x", base="main", title="t", body="b", token="")


async def test_open_pr_same_head_and_base() -> None:
    with pytest.raises(PRError):
        await pm.open_pr("a/b", head="main", base="main", title="t", body="b", token="tkn")


async def test_open_pr_wraps_github_exception(monkeypatch) -> None:
    from github import GithubException

    repo = MagicMock()
    repo.get_pulls.side_effect = GithubException(422, {"message": "boom"}, None)
    _fake_github(monkeypatch, repo)

    with pytest.raises(PRError):
        await pm.open_pr("a/b", head="x", base="main", title="t", body="b", token="tkn")

"""Tests for config.settings loading and validation."""
from __future__ import annotations

import importlib

import pytest


_ENV = {
    "GROQ_API_KEY": "g",
    "TELEGRAM_BOT_TOKEN": "t",
    "TELEGRAM_ALLOWED_USER_IDS": "1,2, 3",
    "GITHUB_TOKEN": "gh",
    "E2B_API_KEY": "e",
}


def _reload(monkeypatch, env):
    """Apply env and reimport the settings module fresh."""
    for k in (
        "GROQ_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "GITHUB_TOKEN",
        "E2B_API_KEY",
        "GITHUB_DEFAULT_BRANCH",
        "LOG_LEVEL",
        "MAX_TEST_RETRIES",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config.settings as s

    return importlib.reload(s)


def test_load_ok(monkeypatch):
    s = _reload(monkeypatch, _ENV)
    cfg = s.load()
    assert cfg.telegram_allowed_user_ids == (1, 2, 3)
    assert cfg.github_default_branch == "main"
    assert cfg.max_test_retries == 3
    assert cfg.verify().startswith("OK:")


def test_missing_key_raises(monkeypatch):
    env = dict(_ENV)
    env.pop("GROQ_API_KEY")
    s = _reload(monkeypatch, env)
    with pytest.raises(s.SettingsError):
        s.load()


def test_malformed_user_ids_raises(monkeypatch):
    env = dict(_ENV, TELEGRAM_ALLOWED_USER_IDS="abc,1")
    s = _reload(monkeypatch, env)
    with pytest.raises(s.SettingsError):
        s.load()

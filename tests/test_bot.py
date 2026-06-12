"""Tests for bot.commands, bot.keyboards, and bot.handler wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import commands, keyboards


def _ctx(args: list[str] | None = None) -> SimpleNamespace:
    """Build a minimal PTB-like context with args, user_data, and a mock bot."""
    return SimpleNamespace(
        args=args or [],
        user_data={},
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


def _update(chat_id: int = 42, text: str | None = None) -> SimpleNamespace:
    """Build a minimal PTB-like Update with a chat, user, and optional message."""
    msg = SimpleNamespace(text=text) if text is not None else None
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=7),
        effective_message=msg,
    )


# ---------- URL parsing ----------


@pytest.mark.parametrize(
    "url,slug",
    [
        ("https://github.com/foo/bar", "foo/bar"),
        ("https://github.com/foo/bar.git", "foo/bar"),
        ("https://github.com/foo/bar/", "foo/bar"),
        ("http://github.com/a_b/c-d.e", "a_b/c-d.e"),
    ],
)
def test_parse_repo_url_ok(url: str, slug: str) -> None:
    assert commands.parse_repo_url(url) == slug


@pytest.mark.parametrize("bad", ["", "github.com/x/y", "https://gitlab.com/x/y", "not a url"])
def test_parse_repo_url_bad(bad: str) -> None:
    with pytest.raises(commands.RepoUrlError):
        commands.parse_repo_url(bad)


# ---------- Command callbacks ----------


async def test_start_sends_help() -> None:
    upd, ctx = _update(), _ctx()
    await commands.start(upd, ctx)
    ctx.bot.send_message.assert_awaited_once()
    assert "ClawCode online" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_set_repo_stores_slug() -> None:
    upd, ctx = _update(), _ctx(args=["https://github.com/foo/bar"])
    await commands.set_repo(upd, ctx)
    assert ctx.user_data["repo"] == "foo/bar"
    assert ctx.user_data["status"] == "idle"
    assert ctx.user_data["history"] == ["repo set: foo/bar"]
    assert "Repo set: foo/bar" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_set_repo_rejects_bad_url() -> None:
    upd, ctx = _update(), _ctx(args=["nope"])
    await commands.set_repo(upd, ctx)
    assert "repo" not in ctx.user_data
    assert "Invalid" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_set_repo_missing_arg() -> None:
    upd, ctx = _update(), _ctx(args=[])
    await commands.set_repo(upd, ctx)
    assert "Usage" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_status_defaults_idle() -> None:
    upd, ctx = _update(), _ctx()
    await commands.status(upd, ctx)
    assert ctx.bot.send_message.await_args.kwargs["text"] == "idle"


async def test_history_empty_then_populated() -> None:
    upd, ctx = _update(), _ctx()
    await commands.history(upd, ctx)
    assert ctx.bot.send_message.await_args.kwargs["text"] == "(empty)"

    ctx.user_data["history"] = ["a", "b"]
    await commands.history(upd, ctx)
    assert ctx.bot.send_message.await_args.kwargs["text"] == "a\nb"


async def test_cancel_sets_idle_and_logs() -> None:
    upd, ctx = _update(), _ctx()
    ctx.user_data["status"] = "running"
    await commands.cancel(upd, ctx)
    assert ctx.user_data["status"] == "idle"
    assert ctx.user_data["history"] == ["cancelled"]


async def test_resume_requires_arg() -> None:
    upd, ctx = _update(), _ctx()
    ctx.application = SimpleNamespace(bot_data={})
    await commands.resume(upd, ctx)
    assert "Usage" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_resume_no_dispatcher_replies_friendly() -> None:
    upd, ctx = _update(), _ctx(args=["task-1"])
    ctx.application = SimpleNamespace(bot_data={})
    await commands.resume(upd, ctx)
    assert "not wired" in ctx.bot.send_message.await_args.kwargs["text"]
    assert ctx.user_data["history"] == ["resume: task-1"]


async def test_resume_invokes_dispatcher() -> None:
    upd, ctx = _update(), _ctx(args=["task-1"])
    hook = AsyncMock()
    ctx.application = SimpleNamespace(bot_data={"resume_task": hook})
    await commands.resume(upd, ctx)
    hook.assert_awaited_once_with("task-1", upd, ctx)


async def test_voice_no_transcriber_replies_friendly() -> None:
    upd = SimpleNamespace(
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7),
        effective_message=SimpleNamespace(voice=SimpleNamespace(file_id="f1")),
    )
    ctx = _ctx()
    ctx.application = SimpleNamespace(bot_data={})
    await commands.voice(upd, ctx)
    assert "not wired" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_voice_dispatch_happy_path() -> None:
    upd = SimpleNamespace(
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7),
        effective_message=SimpleNamespace(voice=SimpleNamespace(file_id="f1")),
    )
    ctx = _ctx()
    fake = AsyncMock(return_value="say hi")
    ctx.application = SimpleNamespace(bot_data={"transcribe_voice": fake})
    await commands.voice(upd, ctx)
    fake.assert_awaited_once()
    assert "transcript: say hi" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_echo_prefixes() -> None:
    upd, ctx = _update(text="hello"), _ctx()
    await commands.echo(upd, ctx)
    assert ctx.bot.send_message.await_args.kwargs["text"] == "echo: hello"


# ---------- Keyboards ----------


def test_approval_keyboard_shape() -> None:
    kb = keyboards.approval_keyboard("t-123")
    row = kb.inline_keyboard[0]
    assert [b.text for b in row] == ["Approve", "Reject"]
    assert row[0].callback_data == "approve:t-123"
    assert row[1].callback_data == "reject:t-123"


@pytest.mark.parametrize(
    "data,parsed",
    [("approve:t-1", ("approve", "t-1")), ("reject:abc", ("reject", "abc"))],
)
def test_parse_callback_ok(data: str, parsed: tuple[str, str]) -> None:
    assert keyboards.parse_callback(data) == parsed


@pytest.mark.parametrize("bad", ["", "approve", "foo:bar", "approve:"])
def test_parse_callback_bad(bad: str) -> None:
    with pytest.raises(ValueError):
        keyboards.parse_callback(bad)


# ---------- Handler wiring ----------


def test_build_application_registers_handlers(monkeypatch) -> None:
    # Avoid real Telegram client init.
    import bot.handler as h
    from bot.handler import build_application
    from config.settings import Settings

    class _FakeApp:
        def __init__(self) -> None:
            self.handlers: list = []

        def add_handler(self, handler) -> None:  # noqa: ANN001
            self.handlers.append(handler)

    class _FakeBuilder:
        def token(self, _t: str) -> _FakeBuilder:
            return self

        def build(self) -> _FakeApp:
            return _FakeApp()

    monkeypatch.setattr(h, "ApplicationBuilder", lambda: _FakeBuilder())

    cfg = Settings(
        groq_api_key="g",
        telegram_bot_token="t",
        telegram_allowed_user_ids=(1, 2),
        github_token="gh",
        github_default_branch="main",
        e2b_api_key="e",
        log_level="INFO",
        checkpoint_dir=__import__("pathlib").Path("./checkpoints"),
        chroma_dir=__import__("pathlib").Path("./chroma_data"),
        max_test_retries=3,
    )
    app = build_application(cfg)
    # 6 commands + 1 voice + 1 text echo + 1 deny = 9 handlers
    assert len(app.handlers) == 9

"""Telegram command callbacks. No agent logic — Phase 1 routing only."""

from __future__ import annotations

import logging
import re
from typing import cast

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_REPO_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class RepoUrlError(ValueError):
    """Raised when a /repo argument is not a valid GitHub URL."""


def parse_repo_url(url: str) -> str:
    """Return 'owner/repo' from a GitHub URL; raise RepoUrlError if malformed."""
    m = _REPO_URL_RE.match(url.strip())
    if not m:
        raise RepoUrlError(f"not a github repo url: {url!r}")
    return f"{m['owner']}/{m['repo']}"


def _user_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Return the per-user mutable state dict (PTB-managed, in-memory)."""
    return cast(dict, context.user_data)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user and explain available commands."""
    assert update.effective_chat is not None
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "ClawCode online. Commands:\n"
            "/repo <github url> — set target repo\n"
            "/status — current state\n"
            "/history — recent actions\n"
            "/cancel — clear current task"
        ),
    )


async def set_repo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /repo <url>: validate and store as 'owner/repo' in user_data."""
    assert update.effective_chat is not None
    chat_id = update.effective_chat.id
    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /repo <github url>")
        return
    try:
        slug = parse_repo_url(context.args[0])
    except RepoUrlError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid GitHub URL.")
        return
    state = _user_state(context)
    state["repo"] = slug
    state.setdefault("status", "idle")
    state.setdefault("history", []).append(f"repo set: {slug}")
    await context.bot.send_message(chat_id=chat_id, text=f"Repo set: {slug}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the current status held in user_data (defaults to 'idle')."""
    assert update.effective_chat is not None
    state = _user_state(context)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=state.get("status", "idle"),
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the recent action log (last 10 entries)."""
    assert update.effective_chat is not None
    entries = _user_state(context).get("history", [])
    text = "\n".join(entries[-10:]) if entries else "(empty)"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the current task state for this user."""
    assert update.effective_chat is not None
    state = _user_state(context)
    state["status"] = "idle"
    state.setdefault("history", []).append("cancelled")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Cancelled.")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo any free-text message back. Agent dispatch lands in Phase 4."""
    assert update.effective_chat is not None and update.effective_message is not None
    text = update.effective_message.text or ""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"echo: {text}")

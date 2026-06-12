"""Telegram command callbacks. No agent logic — Phase 1 routing only."""

from __future__ import annotations

import logging
import re
from typing import cast

from telegram import Update
from telegram.ext import ContextTypes

from bot import approval, keyboards

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


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Continue an in-flight task from the latest checkpoint. Usage: /resume <task_id>."""
    assert update.effective_chat is not None
    chat_id = update.effective_chat.id
    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /resume <task_id>")
        return
    task_id = context.args[0]
    state = _user_state(context)
    state.setdefault("history", []).append(f"resume: {task_id}")
    resume_fn = getattr(getattr(context, "application", None), "bot_data", {}).get("resume_task")
    if resume_fn is None:
        await context.bot.send_message(
            chat_id=chat_id, text=f"Resume not wired yet (task {task_id})"
        )
        return
    try:
        await resume_fn(task_id, update, context)
    except Exception as exc:  # noqa: BLE001 — surface friendly error, not stack
        logger.exception("resume failed for %s", task_id)
        await context.bot.send_message(chat_id=chat_id, text=f"Resume failed: {exc}")


async def voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a voice note, then treat the transcript as a task message."""
    assert update.effective_chat is not None and update.effective_message is not None
    chat_id = update.effective_chat.id
    voice_msg = update.effective_message.voice
    if voice_msg is None:
        return
    transcribe_fn = getattr(getattr(context, "application", None), "bot_data", {}).get(
        "transcribe_voice"
    )
    if transcribe_fn is None:
        await context.bot.send_message(chat_id=chat_id, text="Voice not wired yet.")
        return
    try:
        text = await transcribe_fn(context.bot, voice_msg.file_id)
    except Exception as exc:  # noqa: BLE001 — surface friendly error, not stack
        logger.exception("voice transcription failed")
        await context.bot.send_message(chat_id=chat_id, text=f"Voice error: {exc}")
        return
    _user_state(context).setdefault("history", []).append(f"voice: {len(text)} chars")
    await context.bot.send_message(chat_id=chat_id, text=f"transcript: {text}")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve a pending approval ``Future`` based on the operator's button press."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    logger.info("on_callback fired: data=%r from user=%s", query.data, query.from_user.id if query.from_user else "?")
    bot_data = getattr(getattr(context, "application", None), "bot_data", {}) or {}
    gate = bot_data.get("approval_gate")
    secret = bot_data.get("hmac_secret", "")
    if gate is None:
        await query.answer("Approval gate not wired", show_alert=True)
        return
    try:
        action, task_id = keyboards.parse_callback(query.data, hmac_secret=secret)
    except ValueError:
        logger.warning("rejected callback_data (bad/tampered)")
        await query.answer("Invalid request", show_alert=True)
        return
    resolved = approval.resolve(gate, task_id, approved=action == keyboards.APPROVE_PREFIX)
    await query.answer("Recorded" if resolved else "No pending request")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch free text as a task if wired; otherwise echo back."""
    assert update.effective_chat is not None and update.effective_message is not None
    chat_id = update.effective_chat.id
    text = update.effective_message.text or ""
    bot_data = getattr(getattr(context, "application", None), "bot_data", {}) or {}
    dispatch = bot_data.get("dispatch_task")
    state = _user_state(context)
    repo_slug = state.get("repo")
    if dispatch is None or not repo_slug:
        await context.bot.send_message(chat_id=chat_id, text=f"echo: {text}")
        return
    state["status"] = "running"
    try:
        url = await dispatch(repo_slug, text, chat_id)
        await context.bot.send_message(chat_id=chat_id, text=f"PR: {url}")
    except Exception as exc:  # noqa: BLE001 — surface friendly error, not stack
        logger.exception("task dispatch failed")
        await context.bot.send_message(chat_id=chat_id, text=f"Task failed: {exc}")
    finally:
        state["status"] = "idle"
        state.setdefault("history", []).append(f"task: {text[:50]}")

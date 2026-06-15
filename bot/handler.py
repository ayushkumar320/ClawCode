"""PTB Application factory with strict user allowlist enforcement."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import commands
from config.settings import Settings

logger = logging.getLogger(__name__)


def _allow_filter(user_ids: Iterable[int]) -> filters.BaseFilter:
    """Build a PTB filter that admits only the configured user IDs."""
    return filters.User(user_id=list(user_ids))


async def _deny(update: Update, context) -> None:  # noqa: ANN001 — PTB callback signature
    """Log and silently drop any update from a non-allowlisted user."""
    user = update.effective_user
    uid = user.id if user else "?"
    logger.info("denied update from non-allowlisted user_id=%s", uid)


def build_application(settings: Settings) -> Application:
    """Construct the PTB Application with command + echo handlers wired up."""
    app = ApplicationBuilder().token(settings.telegram_bot_token).concurrent_updates(8).build()
    allow = _allow_filter(settings.telegram_allowed_user_ids)

    app.add_handler(CommandHandler("start", commands.start, filters=allow))
    app.add_handler(CommandHandler("repo", commands.set_repo, filters=allow))
    app.add_handler(CommandHandler("status", commands.status, filters=allow))
    app.add_handler(CommandHandler("history", commands.history, filters=allow))
    app.add_handler(CommandHandler("cancel", commands.cancel, filters=allow))
    app.add_handler(CommandHandler("resume", commands.resume, filters=allow))
    app.add_handler(CommandHandler("approve", commands.approve, filters=allow))
    app.add_handler(CommandHandler("reject", commands.reject, filters=allow))
    app.add_handler(MessageHandler(allow & filters.VOICE, commands.voice))
    app.add_handler(MessageHandler(allow & filters.TEXT & ~filters.COMMAND, commands.echo))
    app.add_handler(CallbackQueryHandler(commands.on_callback))
    app.add_handler(MessageHandler(~allow, _deny))

    logger.info(
        "telegram application built; allowlist=%d users", len(settings.telegram_allowed_user_ids)
    )
    return app

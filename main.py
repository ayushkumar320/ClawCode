"""Entry point: validate settings, wire OrchestratorDeps, run the Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from functools import partial

from dotenv import load_dotenv

from agent import checkpoints, wiring
from agent.orchestrator import run_task
from bot import voice as voice_mod
from bot.approval import ApprovalGate, request_approval
from bot.handler import build_application
from config.settings import Settings, SettingsError, get


def setup_logging(cfg: Settings) -> None:
    """Configure stdlib logging from the loaded settings."""
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not cfg.langsmith_tracing:
        logging.getLogger("langchain_core.tracers").setLevel(logging.ERROR)


def make_dispatch(cfg: Settings, gate: ApprovalGate, bot) -> object:
    """Build the per-message ``dispatch_task(repo_slug, prompt, chat_id) -> pr_url`` callable."""

    async def dispatch(repo_slug: str, prompt: str, chat_id: int) -> str:
        task_id = uuid.uuid4().hex[:12]
        await bot.send_message(chat_id=chat_id, text=f"Task started: {task_id}")
        approval_cb = partial(
            request_approval,
            gate,
            bot,
            chat_id,
            hmac_secret=cfg.telegram_bot_token,
        )

        async def approval(tid: str, summary: str) -> bool:
            return await approval_cb(tid, summary)

        deps = wiring.compose_deps(cfg, approval=approval)
        return await run_task(task_id, repo_slug, prompt, deps)

    return dispatch


def make_resume(cfg: Settings, gate: ApprovalGate, bot) -> object:
    """Build the ``/resume <task_id>`` callable used by ``bot.commands.resume``."""

    async def resume(task_id: str, update, context) -> None:
        chat_id = update.effective_chat.id
        saved = await checkpoints.load(task_id, cfg.checkpoint_dir)
        if saved is None:
            await bot.send_message(chat_id=chat_id, text=f"No checkpoint found for {task_id}.")
            return

        async def approval(tid: str, summary: str) -> bool:
            return await request_approval(
                gate, bot, chat_id, tid, summary, hmac_secret=cfg.telegram_bot_token
            )

        deps = wiring.compose_deps(cfg, approval=approval)
        url = await run_task(task_id, saved.repo_slug, saved.user_prompt, deps)
        await bot.send_message(chat_id=chat_id, text=f"PR: {url}")

    return resume


def make_transcriber(cfg: Settings) -> object:
    """Build the ``transcribe_voice(bot, file_id)`` callable for voice messages."""

    async def transcribe(bot, file_id: str) -> str:
        return await voice_mod.transcribe_voice(bot, file_id, groq_api_key=cfg.groq_api_key)

    return transcribe


def wire_application(cfg: Settings):
    """Build the PTB ``Application`` and stash all dispatch hooks in ``bot_data``."""
    app = build_application(cfg)
    gate = ApprovalGate()
    app.bot_data["approval_gate"] = gate
    app.bot_data["hmac_secret"] = cfg.telegram_bot_token
    app.bot_data["allowed_user_ids"] = frozenset(cfg.telegram_allowed_user_ids)
    app.bot_data["active_tasks"] = {}
    app.bot_data["dispatch_task"] = make_dispatch(cfg, gate, app.bot)
    app.bot_data["resume_task"] = make_resume(cfg, gate, app.bot)
    app.bot_data["transcribe_voice"] = make_transcriber(cfg)
    return app


def main() -> int:
    """Boot the bot in long-polling mode; return non-zero on configuration error."""
    load_dotenv()
    try:
        cfg = get()
    except SettingsError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("Configuration error: %s", exc)
        return 1

    setup_logging(cfg)
    log = logging.getLogger(__name__)
    log.info(cfg.verify())

    app = wire_application(cfg)
    log.info("starting Telegram long-polling")
    app.run_polling()
    return 0


# Keep async helpers importable for tests without forcing a real PTB instance.
__all__ = [
    "main",
    "make_dispatch",
    "make_resume",
    "make_transcriber",
    "wire_application",
    "setup_logging",
    "asyncio",
]


if __name__ == "__main__":
    sys.exit(main())

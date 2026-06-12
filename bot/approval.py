"""Approval coordinator: post an inline keyboard, await the operator's click.

State lives in a dataclass-keyed map injected via ``application.bot_data`` —
no module-level globals. Each pending request gets an ``asyncio.Future`` that
the ``CallbackQueryHandler`` resolves on button press.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from bot import keyboards

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_TIMEOUT_S = 600  # 10 minutes


@dataclass
class ApprovalGate:
    """Per-process registry mapping task_id → pending approval Future."""

    waiters: dict[str, asyncio.Future] = field(default_factory=dict)


async def request_approval(
    gate: ApprovalGate,
    bot,
    chat_id: int,
    task_id: str,
    summary: str,
    *,
    hmac_secret: str,
    timeout_s: float = DEFAULT_APPROVAL_TIMEOUT_S,
) -> bool:
    """Send the approval keyboard and wait for the operator's click; True = approved."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    gate.waiters[task_id] = fut
    kb = keyboards.approval_keyboard(task_id, hmac_secret=hmac_secret)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Approve task {task_id}?\n\n{summary}",
            reply_markup=kb,
        )
        return await asyncio.wait_for(fut, timeout=timeout_s)
    except TimeoutError:
        logger.info("approval timed out for task %s", task_id)
        return False
    finally:
        gate.waiters.pop(task_id, None)


def resolve(gate: ApprovalGate, task_id: str, approved: bool) -> bool:
    """Resolve the pending Future for ``task_id``; returns True if a waiter was found."""
    fut = gate.waiters.get(task_id)
    if fut is None or fut.done():
        return False
    fut.set_result(approved)
    return True

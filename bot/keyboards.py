"""Inline keyboard builders. Approval flow stub; real wiring lands in Phase 4."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

APPROVE_PREFIX = "approve"
REJECT_PREFIX = "reject"


def approval_keyboard(task_id: str) -> InlineKeyboardMarkup:
    """Build an approve/reject inline keyboard for a given task id."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"{APPROVE_PREFIX}:{task_id}"),
                InlineKeyboardButton("Reject", callback_data=f"{REJECT_PREFIX}:{task_id}"),
            ]
        ]
    )


def parse_callback(data: str) -> tuple[str, str]:
    """Split callback_data into (action, task_id). Raises ValueError if malformed."""
    if ":" not in data:
        raise ValueError(f"malformed callback_data: {data!r}")
    action, task_id = data.split(":", 1)
    if action not in (APPROVE_PREFIX, REJECT_PREFIX) or not task_id:
        raise ValueError(f"unknown action or empty task_id: {data!r}")
    return action, task_id

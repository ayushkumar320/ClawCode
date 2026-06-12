"""Inline keyboard builders. Callback data is HMAC-signed so a stray group chat
cannot spoof approvals — every payload is verified before dispatch.
"""

from __future__ import annotations

import hashlib
import hmac

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

APPROVE_PREFIX = "approve"
REJECT_PREFIX = "reject"
_TAG_LEN = 10  # truncated HMAC tag — short enough for Telegram's 64-byte callback_data cap


def _tag(action: str, task_id: str, secret: str) -> str:
    """Compute the truncated HMAC-SHA256 tag for ``{action}:{task_id}`` under ``secret``."""
    msg = f"{action}:{task_id}".encode()
    mac = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return mac[:_TAG_LEN]


def _make_cb(action: str, task_id: str, secret: str) -> str:
    """Build the signed ``action:task_id:tag`` callback_data payload."""
    return f"{action}:{task_id}:{_tag(action, task_id, secret)}"


def approval_keyboard(task_id: str, *, hmac_secret: str = "") -> InlineKeyboardMarkup:
    """Build an approve/reject inline keyboard for ``task_id`` with HMAC-signed callbacks."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve", callback_data=_make_cb(APPROVE_PREFIX, task_id, hmac_secret)
                ),
                InlineKeyboardButton(
                    "Reject", callback_data=_make_cb(REJECT_PREFIX, task_id, hmac_secret)
                ),
            ]
        ]
    )


def parse_callback(data: str, *, hmac_secret: str = "") -> tuple[str, str]:
    """Verify the HMAC tag and split into ``(action, task_id)``. Raises ValueError on tamper."""
    parts = data.split(":")
    if len(parts) != 3:
        raise ValueError(f"malformed callback_data: {data!r}")
    action, task_id, tag = parts
    if action not in (APPROVE_PREFIX, REJECT_PREFIX) or not task_id:
        raise ValueError(f"unknown action or empty task_id: {data!r}")
    expected = _tag(action, task_id, hmac_secret)
    if not hmac.compare_digest(tag, expected):
        raise ValueError(f"callback_data tag mismatch for {action}:{task_id}")
    return action, task_id

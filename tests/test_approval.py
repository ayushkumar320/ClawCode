"""Tests for bot.approval — the gate posts a keyboard then awaits a click."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot import approval


async def test_request_approval_resolved_true() -> None:
    gate = approval.ApprovalGate()
    bot = MagicMock()
    bot.send_message = AsyncMock()

    async def driver() -> None:
        await asyncio.sleep(0)  # let the request register the waiter first
        assert approval.resolve(gate, "t-1", approved=True)

    result, _ = await asyncio.gather(
        approval.request_approval(gate, bot, 42, "t-1", "summary", hmac_secret="s"),
        driver(),
    )
    assert result is True
    bot.send_message.assert_awaited_once()


async def test_request_approval_resolved_false() -> None:
    gate = approval.ApprovalGate()
    bot = MagicMock()
    bot.send_message = AsyncMock()

    async def driver() -> None:
        await asyncio.sleep(0)
        approval.resolve(gate, "t-2", approved=False)

    result, _ = await asyncio.gather(
        approval.request_approval(gate, bot, 1, "t-2", "x", hmac_secret="s"),
        driver(),
    )
    assert result is False


async def test_request_approval_timeout_returns_false() -> None:
    gate = approval.ApprovalGate()
    bot = MagicMock()
    bot.send_message = AsyncMock()
    out = await approval.request_approval(
        gate, bot, 1, "t-late", "x", hmac_secret="s", timeout_s=0.05
    )
    assert out is False
    assert "t-late" not in gate.waiters


def test_resolve_unknown_task_is_no_op() -> None:
    gate = approval.ApprovalGate()
    assert approval.resolve(gate, "nope", approved=True) is False


async def test_resolve_already_done_is_no_op() -> None:
    gate = approval.ApprovalGate()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    fut.set_result(True)
    gate.waiters["t"] = fut
    assert approval.resolve(gate, "t", approved=False) is False

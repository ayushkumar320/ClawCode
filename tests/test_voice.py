"""Tests for bot.voice — PTB Bot + Groq Whisper are mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import voice as v


def _fake_bot(payload: bytes = b"oggdata") -> MagicMock:
    file_obj = MagicMock()
    file_obj.download_as_bytearray = AsyncMock(return_value=bytearray(payload))
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=file_obj)
    return bot


def _patch_groq(monkeypatch, *, text: str = "hello there", raises: Exception | None = None) -> None:
    client = MagicMock()
    create = (
        AsyncMock(side_effect=raises)
        if raises
        else AsyncMock(return_value=SimpleNamespace(text=text))
    )
    client.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    monkeypatch.setattr(v, "AsyncGroq", MagicMock(return_value=client))


def test_scrub_removes_key() -> None:
    assert "k" not in v._scrub("oops k here", "k")
    assert v._scrub("plain", None) == "plain"


async def test_transcribe_missing_key() -> None:
    with pytest.raises(v.VoiceError):
        await v.transcribe_voice(_fake_bot(), "f1", groq_api_key="")


async def test_transcribe_happy_path(monkeypatch) -> None:
    _patch_groq(monkeypatch, text="hi world")
    bot = _fake_bot()
    out = await v.transcribe_voice(bot, "f1", groq_api_key="k")
    assert out == "hi world"
    bot.get_file.assert_awaited_once_with("f1")


async def test_transcribe_too_large(monkeypatch) -> None:
    _patch_groq(monkeypatch)
    bot = _fake_bot(payload=b"x" * (v.MAX_VOICE_BYTES + 1))
    with pytest.raises(v.VoiceError):
        await v.transcribe_voice(bot, "f1", groq_api_key="k", max_bytes=v.MAX_VOICE_BYTES)


async def test_transcribe_download_wraps(monkeypatch) -> None:
    _patch_groq(monkeypatch)
    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=RuntimeError("net secret-k"))
    with pytest.raises(v.VoiceError) as ei:
        await v.transcribe_voice(bot, "f1", groq_api_key="secret-k")
    assert "secret-k" not in str(ei.value)


async def test_transcribe_sdk_error_wraps(monkeypatch) -> None:
    _patch_groq(monkeypatch, raises=RuntimeError("boom secret-k"))
    with pytest.raises(v.VoiceError) as ei:
        await v.transcribe_voice(_fake_bot(), "f1", groq_api_key="secret-k")
    assert "secret-k" not in str(ei.value)

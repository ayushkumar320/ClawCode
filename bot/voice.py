"""Telegram voice-note download + Groq Whisper transcription.

The transcript is treated as user task input; the audio bytes never leave
this module. We log byte counts (not content) and scrub the API key from
any error surfacing to upstream callers.
"""

from __future__ import annotations

import logging
from typing import Any

from groq import AsyncGroq  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-large-v3-turbo"
MAX_VOICE_BYTES = 10 * 1024 * 1024  # 10 MiB hard cap


class VoiceError(RuntimeError):
    """Raised on voice download or transcription failure."""


def _scrub(msg: str, api_key: str | None) -> str:
    """Remove the api key from a message before it surfaces in logs or errors."""
    return msg.replace(api_key, "***") if api_key else msg


async def transcribe_voice(
    bot: Any,
    file_id: str,
    *,
    groq_api_key: str,
    timeout_s: float = 60.0,
    max_bytes: int = MAX_VOICE_BYTES,
) -> str:
    """Download a Telegram voice file by id and return the Whisper transcript."""
    if not groq_api_key:
        raise VoiceError("missing GROQ_API_KEY for transcription")
    try:
        file = await bot.get_file(file_id)
        data = await file.download_as_bytearray()
    except Exception as exc:  # noqa: BLE001 — PTB error surface is broad
        raise VoiceError(_scrub(f"voice download failed: {exc}", groq_api_key)) from exc
    if len(data) > max_bytes:
        raise VoiceError(f"voice file too large: {len(data)} > {max_bytes} bytes")
    client = AsyncGroq(api_key=groq_api_key, timeout=timeout_s)
    try:
        resp = await client.audio.transcriptions.create(
            file=("voice.ogg", bytes(data)),
            model=WHISPER_MODEL,
        )
    except Exception as exc:  # noqa: BLE001 — SDK error surface is broad
        raise VoiceError(_scrub(f"transcription failed: {exc}", groq_api_key)) from exc
    text = (getattr(resp, "text", "") or "").strip()
    logger.info("voice transcribed (%d bytes audio → %d chars)", len(data), len(text))
    return text

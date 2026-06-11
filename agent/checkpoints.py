"""Atomic JSON checkpointing of ``AgentState`` under ``settings.checkpoint_dir``."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from agent.exceptions import AgentError
from agent.state import AgentState

logger = logging.getLogger(__name__)


def path_for(directory: Path, task_id: str) -> Path:
    """Return the checkpoint file path for ``task_id`` inside ``directory``."""
    if not task_id or "/" in task_id or task_id.startswith("."):
        raise AgentError(f"invalid task_id: {task_id!r}")
    return directory / f"{task_id}.json"


async def save(state: AgentState, directory: Path) -> Path:
    """Atomically write the state to ``<directory>/<task_id>.json``."""
    target = path_for(directory, state.task_id)
    payload = state.model_dump_json()

    def _write() -> None:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".ckpt-", dir=str(directory))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, target)
        except OSError:
            _safe_unlink(tmp)
            raise

    await asyncio.to_thread(_write)
    return target


def _safe_unlink(p: str) -> None:
    """Best-effort delete of a leftover temp file; ignored on failure."""
    try:
        os.unlink(p)
    except OSError:
        pass


async def load(task_id: str, directory: Path) -> AgentState | None:
    """Return the persisted state or None if the checkpoint is absent."""
    target = path_for(directory, task_id)
    if not target.exists():
        return None
    try:
        raw = await asyncio.to_thread(target.read_text, encoding="utf-8")
        return AgentState.model_validate_json(raw)
    except (OSError, ValidationError) as exc:
        raise AgentError(f"checkpoint load failed: {task_id}: {exc}") from exc


async def clear(task_id: str, directory: Path) -> None:
    """Remove the checkpoint file if it exists; silent on missing."""
    target = path_for(directory, task_id)

    def _rm() -> None:
        try:
            target.unlink()
        except FileNotFoundError:
            return

    await asyncio.to_thread(_rm)

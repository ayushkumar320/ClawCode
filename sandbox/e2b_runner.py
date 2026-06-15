"""Async wrapper around the E2B sandbox for safe per-task pytest execution.

All public functions accept an opaque ``sandbox`` object whose interface
matches ``e2b_code_interpreter.AsyncSandbox`` (``files.write``, ``commands.run``,
``kill``). This lets tests substitute a mock without touching the network.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from e2b.sandbox.commands.command_handle import CommandExitException
from e2b_code_interpreter import AsyncSandbox  # type: ignore[import-not-found]
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from sandbox.exceptions import SandboxError, SandboxTimeoutError


def _is_transient_sandbox_error(exc: BaseException) -> bool:
    """Retry on generic SandboxError but never on a timeout."""
    return isinstance(exc, SandboxError) and not isinstance(exc, SandboxTimeoutError)


logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 256 * 1024
_TRUNCATED_MARK = "\n[...truncated]"
_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "chroma_data", "checkpoints"}
)
_REMOTE_REPO_DIR = "/home/user/repo"


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single sandbox command execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


def _scrub(msg: str, api_key: str | None) -> str:
    """Remove the API key from a message before it surfaces in logs or errors."""
    return msg.replace(api_key, "***") if api_key else msg


def _truncate(text: str) -> str:
    """Cap text at ``MAX_OUTPUT_BYTES`` characters, appending a marker if cut."""
    if len(text) <= MAX_OUTPUT_BYTES:
        return text
    keep = MAX_OUTPUT_BYTES - len(_TRUNCATED_MARK)
    return text[:keep] + _TRUNCATED_MARK


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=1),
    retry=retry_if_exception(_is_transient_sandbox_error),
    reraise=True,
)
async def start_sandbox(api_key: str, *, timeout_s: int = 300) -> Any:
    """Create a fresh E2B sandbox. Returns the SDK's sandbox handle."""
    if not api_key:
        raise SandboxError("missing E2B_API_KEY")
    try:
        return await AsyncSandbox.create(api_key=api_key, timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001 — SDK error surface is broad
        raise SandboxError(_scrub(f"sandbox create failed: {exc}", api_key)) from exc


async def upload_repo(
    sandbox: Any,
    src_dir: Path,
    *,
    remote_dir: str = _REMOTE_REPO_DIR,
    excludes: frozenset[str] = _DEFAULT_EXCLUDES,
) -> int:
    """Upload all files under ``src_dir`` into ``remote_dir``. Returns file count."""
    if not src_dir.is_dir():
        raise SandboxError(f"not a directory: {src_dir}")
    count = 0
    for file in _iter_files(src_dir, excludes):
        rel = file.relative_to(src_dir).as_posix()
        remote_path = f"{remote_dir.rstrip('/')}/{rel}"
        try:
            data = file.read_bytes()
        except OSError as exc:
            raise SandboxError(f"read failed: {rel}: {exc}") from exc
        try:
            await sandbox.files.write(remote_path, data)
        except Exception as exc:  # noqa: BLE001 — SDK error surface is broad
            raise SandboxError(f"upload failed: {rel}: {exc}") from exc
        count += 1
    logger.info("uploaded %d files into %s", count, remote_dir)
    return count


def _iter_files(src_dir: Path, excludes: frozenset[str]):
    """Yield files under src_dir, skipping any path whose parts hit ``excludes``."""
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in excludes for part in path.relative_to(src_dir).parts):
            continue
        yield path


async def install_deps(
    sandbox: Any,
    *,
    timeout_s: int = 120,
    remote_dir: str = _REMOTE_REPO_DIR,
    api_key: str | None = None,
) -> RunResult:
    """Install dependencies inside the sandbox and fail when installation fails."""
    cmd = (
        f"mkdir -p {remote_dir} && cd {remote_dir} && "
        "if [ -f uv.lock ]; then uv sync --frozen; "
        "elif [ -f pyproject.toml ]; then uv sync; "
        "elif [ -f requirements.txt ]; then uv pip install --system -r requirements.txt; "
        "else true; fi"
    )
    result = await _run(
        sandbox,
        cmd,
        timeout_s=timeout_s,
        op="install_deps",
        api_key=api_key,
    )
    if result.exit_code != 0:
        raise SandboxError(
            f"install_deps failed with exit code {result.exit_code}: {result.stderr}"
        )
    return result


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=1),
    retry=retry_if_exception(_is_transient_sandbox_error),
    reraise=True,
)
async def run_pytest(
    sandbox: Any,
    *,
    timeout_s: int = 120,
    remote_dir: str = _REMOTE_REPO_DIR,
    pytest_args: str = "",
    api_key: str | None = None,
) -> RunResult:
    """Execute pytest inside the sandbox; returns exit code + captured output."""
    cmd = (
        f"cd {remote_dir} && "
        f"if [ -f pyproject.toml ] || [ -f uv.lock ]; then uv run pytest {pytest_args}; "
        f"else pytest {pytest_args}; fi"
    ).strip()
    return await _run(sandbox, cmd, timeout_s=timeout_s, op="run_pytest", api_key=api_key)


async def _run(
    sandbox: Any,
    cmd: str,
    *,
    timeout_s: int,
    op: str,
    api_key: str | None,
) -> RunResult:
    """Execute a shell command in the sandbox with timeout + scrubbed errors."""
    if timeout_s <= 0:
        raise SandboxError(f"{op}: timeout_s must be positive")
    start = time.monotonic()
    try:
        res = await sandbox.commands.run(cmd, timeout=timeout_s)
    except TimeoutError as exc:
        raise SandboxTimeoutError(f"{op} exceeded {timeout_s}s") from exc
    except CommandExitException as exc:
        return _exit_result(exc, start)
    except Exception as exc:  # noqa: BLE001 — SDK error surface is broad
        raise SandboxError(_scrub(f"{op} failed: {exc}", api_key)) from exc
    duration = time.monotonic() - start
    return RunResult(
        exit_code=int(getattr(res, "exit_code", 0)),
        stdout=_truncate(getattr(res, "stdout", "") or ""),
        stderr=_truncate(getattr(res, "stderr", "") or ""),
        duration_s=duration,
    )


def _exit_result(exc: CommandExitException, start: float) -> RunResult:
    """Convert an E2B nonzero command exit into a normal command result."""
    error = getattr(exc, "error", "") or ""
    stderr = getattr(exc, "stderr", "") or error
    return RunResult(
        exit_code=int(exc.exit_code),
        stdout=_truncate(getattr(exc, "stdout", "") or ""),
        stderr=_truncate(stderr),
        duration_s=time.monotonic() - start,
    )


async def shutdown(sandbox: Any) -> None:
    """Kill the sandbox; idempotent — failures are logged and swallowed."""
    if sandbox is None:
        return
    try:
        await sandbox.kill()
    except Exception as exc:  # noqa: BLE001 — SDK error surface is broad
        logger.warning("sandbox shutdown raised (ignored): %s", exc)

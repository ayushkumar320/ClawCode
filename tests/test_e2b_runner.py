"""Unit tests for sandbox.e2b_runner — the E2B SDK is fully mocked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sandbox import e2b_runner as er
from sandbox.exceptions import SandboxError, SandboxTimeoutError


def _fake_sandbox(run_result: object | None = None) -> MagicMock:
    """Build a mock sandbox with async ``files.write``, ``commands.run``, ``kill``."""
    sb = MagicMock()
    sb.files = SimpleNamespace(write=AsyncMock())
    sb.commands = SimpleNamespace(
        run=AsyncMock(return_value=run_result or SimpleNamespace(exit_code=0, stdout="", stderr=""))
    )
    sb.kill = AsyncMock()
    return sb


# ---------- helpers ----------


def test_scrub_removes_api_key() -> None:
    assert "k" not in er._scrub("token=k here", "k")
    assert er._scrub("plain", None) == "plain"


def test_truncate_short_unchanged() -> None:
    assert er._truncate("abc") == "abc"


def test_truncate_long_marked() -> None:
    big = "x" * (er.MAX_OUTPUT_BYTES + 50)
    out = er._truncate(big)
    assert len(out) == er.MAX_OUTPUT_BYTES
    assert out.endswith("[...truncated]")


# ---------- start_sandbox ----------


async def test_start_sandbox_missing_key() -> None:
    with pytest.raises(SandboxError):
        await er.start_sandbox("")


async def test_start_sandbox_calls_sdk(monkeypatch) -> None:
    created = MagicMock()
    monkeypatch.setattr(er.AsyncSandbox, "create", AsyncMock(return_value=created))
    out = await er.start_sandbox("k", timeout_s=10)
    assert out is created
    er.AsyncSandbox.create.assert_awaited_once_with(api_key="k", timeout=10)


async def test_start_sandbox_wraps_and_scrubs(monkeypatch) -> None:
    monkeypatch.setattr(er.AsyncSandbox, "create", AsyncMock(side_effect=RuntimeError("oops k")))
    with pytest.raises(SandboxError) as ei:
        await er.start_sandbox("k")
    assert "k" not in str(ei.value)
    assert "***" in str(ei.value)


# ---------- upload_repo ----------


async def test_upload_repo_skips_excludes(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "also.py").write_text("y")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "z.pyc").write_text("c")

    sb = _fake_sandbox()
    count = await er.upload_repo(sb, tmp_path)
    assert count == 2
    written = [c.args[0] for c in sb.files.write.await_args_list]
    assert all(".git" not in p and "__pycache__" not in p for p in written)


async def test_upload_repo_not_a_dir(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_text("x")
    with pytest.raises(SandboxError):
        await er.upload_repo(_fake_sandbox(), f)


async def test_upload_repo_wraps_sdk_error(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x")
    sb = _fake_sandbox()
    sb.files.write.side_effect = RuntimeError("net")
    with pytest.raises(SandboxError):
        await er.upload_repo(sb, tmp_path)


# ---------- _run / install_deps / run_pytest ----------


async def test_run_returns_result_with_duration() -> None:
    sb = _fake_sandbox(SimpleNamespace(exit_code=0, stdout="ok", stderr=""))
    res = await er.run_pytest(sb, timeout_s=5)
    assert res.exit_code == 0
    assert res.stdout == "ok"
    assert res.duration_s >= 0


async def test_run_truncates_output() -> None:
    big = "x" * (er.MAX_OUTPUT_BYTES + 10)
    sb = _fake_sandbox(SimpleNamespace(exit_code=1, stdout=big, stderr=big))
    res = await er.run_pytest(sb, timeout_s=5)
    assert res.stdout.endswith("[...truncated]")
    assert res.stderr.endswith("[...truncated]")


async def test_run_timeout_raises() -> None:
    sb = _fake_sandbox()
    sb.commands.run.side_effect = TimeoutError()
    with pytest.raises(SandboxTimeoutError):
        await er.run_pytest(sb, timeout_s=1)


async def test_run_wraps_and_scrubs() -> None:
    sb = _fake_sandbox()
    sb.commands.run.side_effect = RuntimeError("boom secret-k")
    with pytest.raises(SandboxError) as ei:
        await er.run_pytest(sb, timeout_s=1, api_key="secret-k")
    assert "secret-k" not in str(ei.value)


async def test_invalid_timeout_rejected() -> None:
    with pytest.raises(SandboxError):
        await er.run_pytest(_fake_sandbox(), timeout_s=0)


async def test_install_deps_invokes_shell() -> None:
    sb = _fake_sandbox(SimpleNamespace(exit_code=0, stdout="", stderr=""))
    await er.install_deps(sb, timeout_s=10)
    cmd = sb.commands.run.await_args.args[0]
    assert "uv sync" in cmd and "pip install" in cmd


# ---------- shutdown ----------


async def test_shutdown_calls_kill() -> None:
    sb = _fake_sandbox()
    await er.shutdown(sb)
    sb.kill.assert_awaited_once()


async def test_shutdown_idempotent_on_none() -> None:
    await er.shutdown(None)  # must not raise


async def test_shutdown_swallows_errors(caplog) -> None:
    sb = _fake_sandbox()
    sb.kill.side_effect = RuntimeError("already gone")
    await er.shutdown(sb)  # must not raise

"""LangChain ``@tool`` definitions used by the LangGraph orchestrator.

Each tool reads its repo handle / sandbox / api-key from the per-invocation
``RunnableConfig`` injected by the orchestrator. No global state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict

from gh import repo_manager as rm
from sandbox import e2b_runner as er

logger = logging.getLogger(__name__)


class _StrictArgs(BaseModel):
    """Base for tool-arg models; rejects extras since LLM output is untrusted."""

    model_config = ConfigDict(extra="forbid")


def _cfg(config: RunnableConfig, key: str) -> Any:
    """Pull a required value out of ``config['configurable']``."""
    cfg = (config or {}).get("configurable", {}) if config else {}
    if key not in cfg:
        raise KeyError(f"missing configurable: {key}")
    return cfg[key]


@tool
async def list_files(config: RunnableConfig) -> str:
    """List tracked file paths in the working repo."""
    repo = _cfg(config, "repo")
    return json.dumps({"files": await rm.list_files(repo)})


@tool
async def read_file(path: str, config: RunnableConfig) -> str:
    """Read a UTF-8 file relative to the repo root."""
    repo = _cfg(config, "repo")
    return json.dumps({"content": await rm.read_file(repo, path)})


@tool
async def write_file(path: str, content: str, config: RunnableConfig) -> str:
    """Overwrite a UTF-8 file relative to the repo root, creating parents."""
    repo = _cfg(config, "repo")
    await rm.write_file(repo, path, content)
    return json.dumps({"ok": True})


@tool
async def run_tests(config: RunnableConfig) -> str:
    """Execute pytest inside the E2B sandbox and return exit code + output."""
    repo = _cfg(config, "repo")
    sandbox = _cfg(config, "sandbox")
    api_key = (config or {}).get("configurable", {}).get("e2b_api_key")
    await er.upload_repo(sandbox, repo.path)
    await er.install_deps(sandbox, timeout_s=120, api_key=api_key)
    res = await er.run_pytest(sandbox, timeout_s=120, api_key=api_key)
    return json.dumps({"exit_code": res.exit_code, "stdout": res.stdout, "stderr": res.stderr})


@tool
async def task_complete(summary: str, lesson: str = "") -> str:
    """Signal the task is done; provide a one-sentence summary and optional lesson."""
    return json.dumps({"summary": summary, "lesson": lesson})


TOOLS: tuple = (list_files, read_file, write_file, run_tests, task_complete)
TOOLS_BY_NAME: dict[str, Any] = {t.name: t for t in TOOLS}

"""Agent tool schemas + dispatch. Pure plumbing — no LLM calls live here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from agent.exceptions import ToolArgsError, UnknownTool
from gh import repo_manager as rm
from gh.repo_manager import RepoHandle
from sandbox import e2b_runner as er

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Resources every tool needs: cloned repo handle + live sandbox."""

    repo: RepoHandle
    sandbox: Any
    e2b_api_key: str | None = None


# ---- Argument models ---------------------------------------------------------


class _StrictArgs(BaseModel):
    """Base for tool-arg models — extras forbidden (LLM output is untrusted)."""

    model_config = ConfigDict(extra="forbid")


class _NoArgs(_StrictArgs):
    pass


class _ReadArgs(_StrictArgs):
    path: str


class _WriteArgs(_StrictArgs):
    path: str
    content: str


class _CompleteArgs(_StrictArgs):
    summary: str
    lesson: str = ""


_ARG_MODELS: dict[str, type[BaseModel]] = {
    "list_files": _NoArgs,
    "read_file": _ReadArgs,
    "write_file": _WriteArgs,
    "run_tests": _NoArgs,
    "task_complete": _CompleteArgs,
}


# ---- OpenAI-style tool schemas for the Groq API ------------------------------

TOOL_SCHEMAS: tuple[dict, ...] = (
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List tracked files in the repo.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 file relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Overwrite a UTF-8 file relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run pytest inside the E2B sandbox.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Signal the task is done. Provide a summary + optional lesson.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "lesson": {"type": "string"},
                },
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
    },
)


def _parse_args(name: str, raw: str) -> BaseModel:
    """Validate a raw JSON argument string against the tool's pydantic model."""
    model = _ARG_MODELS.get(name)
    if model is None:
        raise UnknownTool(f"unknown tool: {name}")
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ToolArgsError(f"{name}: arguments not valid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ToolArgsError(f"{name}: {exc.errors()}") from exc


async def dispatch(name: str, raw_args: str, ctx: ToolContext) -> dict[str, Any]:
    """Validate args and route to the matching handler. Returns a JSON-safe dict."""
    args = _parse_args(name, raw_args)
    if name == "list_files":
        return {"files": await rm.list_files(ctx.repo)}
    if name == "read_file":
        a = args  # type: ignore[assignment]
        return {"content": await rm.read_file(ctx.repo, a.path)}  # type: ignore[attr-defined]
    if name == "write_file":
        a = args  # type: ignore[assignment]
        await rm.write_file(ctx.repo, a.path, a.content)  # type: ignore[attr-defined]
        return {"ok": True}
    if name == "run_tests":
        res = await er.run_pytest(ctx.sandbox, timeout_s=120, api_key=ctx.e2b_api_key)
        return {"exit_code": res.exit_code, "stdout": res.stdout, "stderr": res.stderr}
    if name == "task_complete":
        a = args  # type: ignore[assignment]
        return {"summary": a.summary, "lesson": a.lesson}  # type: ignore[attr-defined]
    raise UnknownTool(f"unknown tool: {name}")  # pragma: no cover — guarded by _parse_args

"""Agent orchestration loop — Groq tool-calling per CLAUDE.md §7.

The loop owns no Telegram, GitHub, or Groq clients directly; everything is
injected via ``OrchestratorDeps`` so unit tests can substitute fakes.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent import checkpoints as ckpt
from agent import tools as agent_tools
from agent.exceptions import MaxRetriesExceeded, UserRejected
from agent.llm import AssistantTurn, ToolCall
from agent.state import AgentState
from agent.tools import ToolContext
from gh.repo_manager import RepoHandle

logger = logging.getLogger(__name__)

ChatFn = Callable[[list[dict], tuple[dict, ...], str], Awaitable[AssistantTurn]]
SetupFn = Callable[[str, str], Awaitable[tuple[RepoHandle, Any]]]
TeardownFn = Callable[[Any], Awaitable[None]]
PublishFn = Callable[[RepoHandle, str, str, str], Awaitable[str]]
ApprovalFn = Callable[[str, str], Awaitable[bool]]


@dataclass
class OrchestratorDeps:
    """Injected resources / callbacks used by ``run_task``."""

    chat: ChatFn
    setup: SetupFn
    teardown: TeardownFn
    publish: PublishFn
    approval: ApprovalFn
    checkpoint_dir: Path
    e2b_api_key: str | None = None
    max_retries: int = 3


def classify_effort(prompt: str) -> str:
    """Return ``'none'`` for short single-file edits; ``'default'`` otherwise."""
    p = prompt.strip().lower()
    short = len(p.split()) <= 20
    single = sum(1 for kw in ("file", "function", "module") if kw in p) <= 1
    light_verb = any(v in p for v in ("add", "fix", "rename", "tweak"))
    return "none" if short and single and light_verb else "default"


def build_initial_messages(repo_slug: str, prompt: str) -> list[dict]:
    """Construct the seed message list sent on the first LLM turn."""
    sys = (
        "You are ClawCode, a careful coding agent. Operate only via tool calls. "
        "When done, call task_complete with a 1-sentence summary."
    )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": f"Repository: {repo_slug}\nTask: {prompt}"},
    ]


def _assistant_msg(turn: AssistantTurn) -> dict:
    """Translate an AssistantTurn into a chat-format assistant message dict."""
    return turn.raw_message


def _tool_msg(call_id: str, result: dict) -> dict:
    """Build a ``role=tool`` message carrying a JSON-encoded result."""
    import json

    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)}


def _nudge_msg() -> dict:
    """System nudge when the model replies without calling any tool."""
    return {"role": "system", "content": "You must call a tool or task_complete."}


async def run_task(
    task_id: str,
    repo_slug: str,
    user_prompt: str,
    deps: OrchestratorDeps,
) -> str:
    """Drive the tool-calling loop to completion; return the resulting PR URL."""
    state = await ckpt.load(task_id, deps.checkpoint_dir) or AgentState(
        task_id=task_id, repo_slug=repo_slug, user_prompt=user_prompt
    )
    if not state.messages:
        state.messages = build_initial_messages(repo_slug, user_prompt)
    effort = classify_effort(user_prompt)
    repo, sandbox = await deps.setup(task_id, repo_slug)
    try:
        return await _drive(state, effort, repo, sandbox, deps)
    finally:
        await deps.teardown(sandbox)


async def _drive(
    state: AgentState,
    effort: str,
    repo: RepoHandle,
    sandbox: Any,
    deps: OrchestratorDeps,
) -> str:
    """Inner loop: one LLM turn per iteration, terminates on task_complete."""
    ctx = ToolContext(repo=repo, sandbox=sandbox, e2b_api_key=deps.e2b_api_key)
    while True:
        turn = await deps.chat(state.messages, agent_tools.TOOL_SCHEMAS, effort)
        state.messages.append(_assistant_msg(turn))
        if not turn.tool_calls:
            state.messages.append(_nudge_msg())
            continue
        for call in turn.tool_calls:
            pr_url = await _handle_call(call, state, ctx, deps)
            if pr_url is not None:
                return pr_url


async def _handle_call(
    call: ToolCall,
    state: AgentState,
    ctx: ToolContext,
    deps: OrchestratorDeps,
) -> str | None:
    """Dispatch one tool call, update retries, and surface terminal outcomes."""
    result = await agent_tools.dispatch(call.name, call.arguments, ctx)
    state.messages.append(_tool_msg(call.id, result))
    await ckpt.save(state, deps.checkpoint_dir)

    if call.name == "run_tests":
        if result["exit_code"] == 0:
            state.retries = 0
        else:
            state.retries += 1
            if state.retries > deps.max_retries:
                raise MaxRetriesExceeded(f"{state.task_id}: {deps.max_retries} retries exhausted")
        await ckpt.save(state, deps.checkpoint_dir)

    if call.name == "task_complete":
        return await _finalize(result, state, ctx.repo, deps)
    return None


async def _finalize(
    result: dict,
    state: AgentState,
    repo: RepoHandle,
    deps: OrchestratorDeps,
) -> str:
    """Gate on operator approval, then push the branch and open the PR."""
    summary = result["summary"]
    approved = await deps.approval(state.task_id, summary)
    if not approved:
        raise UserRejected(state.task_id)
    branch = f"agent/{state.task_id}"
    pr_url = await deps.publish(repo, branch, summary, result.get("lesson", ""))
    await ckpt.clear(state.task_id, deps.checkpoint_dir)
    logger.info("task %s completed: %s", state.task_id, pr_url)
    return pr_url

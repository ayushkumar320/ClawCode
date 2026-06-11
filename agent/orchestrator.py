"""LangGraph orchestrator: chat → tools → post_tools → {chat | finalize | abort}.

The compiled ``graph`` is exposed at module scope so LangGraph Studio
(``langgraph dev``) can load it from ``langgraph.json``. LangSmith traces
each node automatically when the ``LANGCHAIN_*`` env vars are set.
"""

import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from agent.exceptions import MaxRetriesExceeded, UserRejected
from agent.llm import build_chat_model
from agent.state import GraphState
from agent.tools import TOOLS
from gh.repo_manager import RepoHandle

logger = logging.getLogger(__name__)

SetupFn = Callable[[str, str], Awaitable[tuple[RepoHandle, Any]]]
TeardownFn = Callable[[Any], Awaitable[None]]
PublishFn = Callable[[RepoHandle, str, str, str], Awaitable[str]]
ApprovalFn = Callable[[str, str], Awaitable[bool]]


@dataclass
class OrchestratorDeps:
    """Injected resources / callbacks supplied per ``run_task`` invocation."""

    setup: SetupFn
    teardown: TeardownFn
    publish: PublishFn
    approval: ApprovalFn
    groq_api_key: str
    e2b_api_key: str | None = None
    max_retries: int = 3
    model: str = "qwen/qwen3-32b"


def classify_effort(prompt: str) -> str:
    """Return ``'none'`` for short single-file edits, ``'default'`` otherwise."""
    p = prompt.strip().lower()
    short = len(p.split()) <= 20
    single = sum(1 for kw in ("file", "function", "module") if kw in p) <= 1
    light_verb = any(v in p for v in ("add", "fix", "rename", "tweak"))
    return "none" if short and single and light_verb else "default"


def build_initial_messages(repo_slug: str, prompt: str) -> list[Any]:
    """Construct the seed message list for the first ``chat`` node invocation."""
    sys = (
        "You are ClawCode, a careful coding agent. Operate only via tool calls. "
        "When done, call task_complete with a 1-sentence summary."
    )
    return [
        SystemMessage(content=sys),
        HumanMessage(content=f"Repository: {repo_slug}\nTask: {prompt}"),
    ]


# ---- Nodes -----------------------------------------------------------------


async def chat_node(state: GraphState, config: RunnableConfig | None = None) -> dict:
    """Invoke the bound ChatGroq model on the current message log."""
    model = (config or {}).get("configurable", {}).get("model")
    if model is None:
        raise RuntimeError("chat_node: 'model' missing in config.configurable")
    resp = await model.ainvoke(state["messages"], config=config)
    return {"messages": [resp]}


async def nudge_node(state: GraphState, config: RunnableConfig | None = None) -> dict:
    """Inject a system nudge when the model replied without calling a tool."""
    return {"messages": [SystemMessage(content="You must call a tool or task_complete.")]}


async def post_tools_node(state: GraphState, config: RunnableConfig | None = None) -> dict:
    """Update ``retries`` based on the latest ``run_tests`` ToolMessage."""
    last_tool_msgs = _last_tool_messages(state["messages"])
    retries = int(state.get("retries", 0) or 0)
    for tm in last_tool_msgs:
        if tm.name != "run_tests":
            continue
        try:
            payload = json.loads(tm.content)
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("exit_code", 1) == 0:
            retries = 0
        else:
            retries += 1
    return {"retries": retries}


async def abort_node(state: GraphState, config: RunnableConfig | None = None) -> dict:
    """Terminal node reached when the test-retry budget is exhausted."""
    raise MaxRetriesExceeded(f"{state.get('task_id')}: max retries exhausted")


async def finalize_node(state: GraphState, config: RunnableConfig | None = None) -> dict:
    """Approval gate → publish branch + PR → return the PR URL."""
    cfg = (config or {}).get("configurable", {}) if config else {}
    approval = cfg["approval"]
    publish = cfg["publish"]
    repo = cfg["repo"]
    last = state["messages"][-1]
    payload = _safe_json(last.content if isinstance(last, ToolMessage) else "{}")
    summary = payload.get("summary", "")
    if not await approval(state["task_id"], summary):
        raise UserRejected(state["task_id"])
    branch = f"agent/{state['task_id']}"
    pr_url = await publish(repo, branch, summary, payload.get("lesson", ""))
    logger.info("task %s completed: %s", state["task_id"], pr_url)
    return {"pr_url": pr_url}


# ---- Routers ---------------------------------------------------------------


def route_after_chat(state: GraphState) -> str:
    """Send tool-calling AI messages to the tools node; otherwise nudge."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return "nudge"


def route_after_post_tools(state: GraphState, config: RunnableConfig | None = None) -> str:
    """Decide whether to finalize, abort on retries, or loop back to chat."""
    cfg = (config or {}).get("configurable", {}) if config else {}
    max_retries = int(cfg.get("max_retries", 3))
    if int(state.get("retries", 0) or 0) > max_retries:
        return "abort"
    for tm in reversed(_last_tool_messages(state["messages"])):
        if tm.name == "task_complete":
            return "finalize"
    return "chat"


# ---- Helpers ---------------------------------------------------------------


def _last_tool_messages(messages: list[Any]) -> list[ToolMessage]:
    """Return the trailing run of ToolMessages produced by the latest tools step."""
    out: list[ToolMessage] = []
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            out.append(m)
            continue
        break
    out.reverse()
    return out


def _safe_json(raw: str) -> dict:
    """Parse JSON, returning an empty dict on failure (tool payloads only)."""
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


# ---- Graph compilation ------------------------------------------------------


class _ConfigSchema(TypedDict, total=False):
    """Per-invocation knobs LangGraph propagates to every node + tool."""

    model: Any
    repo: Any
    sandbox: Any
    approval: Any
    publish: Any
    e2b_api_key: str | None
    max_retries: int
    thread_id: str


def _build_graph() -> Any:
    """Wire up nodes + conditional edges and compile with an in-memory checkpointer."""
    g: StateGraph = StateGraph(GraphState, context_schema=_ConfigSchema)
    g.add_node("chat", chat_node)
    g.add_node("tools", ToolNode(list(TOOLS)))
    g.add_node("post_tools", post_tools_node)
    g.add_node("nudge", nudge_node)
    g.add_node("finalize", finalize_node)
    g.add_node("abort", abort_node)

    g.set_entry_point("chat")
    g.add_conditional_edges("chat", route_after_chat, {"tools": "tools", "nudge": "nudge"})
    g.add_edge("nudge", "chat")
    g.add_edge("tools", "post_tools")
    g.add_conditional_edges(
        "post_tools",
        route_after_post_tools,
        {"chat": "chat", "finalize": "finalize", "abort": "abort"},
    )
    g.add_edge("finalize", END)
    g.add_edge("abort", END)
    return g.compile(checkpointer=MemorySaver())


graph = _build_graph()


# ---- run_task: same surface as Phase 4, now backed by the graph -----------


async def run_task(
    task_id: str,
    repo_slug: str,
    user_prompt: str,
    deps: OrchestratorDeps,
) -> str:
    """Execute one agent task end-to-end. Returns the merged PR URL."""
    repo, sandbox = await deps.setup(task_id, repo_slug)
    model = build_chat_model(
        api_key=deps.groq_api_key,
        model=deps.model,
        reasoning_effort=classify_effort(user_prompt),
    )
    initial: GraphState = {
        "task_id": task_id,
        "repo_slug": repo_slug,
        "user_prompt": user_prompt,
        "messages": build_initial_messages(repo_slug, user_prompt),
        "retries": 0,
    }
    config = {
        "configurable": {
            "thread_id": task_id,
            "model": model,
            "repo": repo,
            "sandbox": sandbox,
            "approval": deps.approval,
            "publish": deps.publish,
            "e2b_api_key": deps.e2b_api_key,
            "max_retries": deps.max_retries,
        },
        "tags": _trace_tags(task_id, repo_slug),
    }
    try:
        final = await graph.ainvoke(initial, config=config)
        pr_url = final.get("pr_url")
        if not pr_url:
            raise RuntimeError("graph returned without pr_url")
        return pr_url
    finally:
        await deps.teardown(sandbox)


def _trace_tags(task_id: str, repo_slug: str) -> list[str]:
    """Tag every LangSmith run with task + repo for searchability."""
    project = os.getenv("LANGCHAIN_PROJECT", "clawcode")
    return [f"task:{task_id}", f"repo:{repo_slug}", f"project:{project}"]

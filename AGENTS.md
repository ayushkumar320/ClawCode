# AGENTS.md

## 1. Project Identity

Telegram-controlled autonomous coding agent. User sends a task via Telegram → agent reads a GitHub repo, plans, writes code, runs tests in an E2B sandbox, self-corrects on failures, and opens a PR after explicit Telegram approval. Solves the problem of dispatching real coding work from a phone without trusting an agent to merge unsupervised.

## 2. Tech Stack Reference

| Component | Tool | Version | Reason |
|---|---|---|---|
| LLM | Groq `qwen/qwen3-32b` | API | Free, native tool calling, `reasoning_effort` toggle |
| Telegram | `python-telegram-bot` | 21.x | Async, mature, webhook + polling |
| GitHub API | `PyGithub` | 2.3+ | PR + repo management |
| Git ops | `GitPython` | 3.1+ | Local branch/commit/push |
| Sandbox | `e2b-code-interpreter` | 1.x | Firecracker microVM, free hobby tier |
| Vector store | `chromadb` | 0.5+ | Local, embedded, no server |
| Embeddings | `sentence-transformers` | 3.x | `all-MiniLM-L6-v2` |
| Voice | Groq `whisper-large-v3-turbo` | API | Fast, free |
| Config | `python-dotenv` | 1.x | `.env` loading |
| Tests | `pytest` + `pytest-asyncio` | latest | Async test support |
| Logging | stdlib `logging` | — | No third-party logger |
| Deploy | Railway.app | — | Free tier, webhook support |

## 3. Architecture Overview

```
┌──────────┐  msg/voice   ┌─────────────┐   tool calls   ┌──────────────┐
│ Telegram │ ───────────► │ bot/handler │ ─────────────► │ orchestrator │
│   user   │ ◄─────────── │  (PTB v21)  │ ◄───────────── │  (Qwen3-32B) │
└──────────┘   approve    └─────────────┘  status/diff   └──────┬───────┘
                                                                │
                          ┌─────────────────────────────────────┼──────────────┐
                          ▼                                     ▼              ▼
                   ┌────────────┐                       ┌──────────────┐  ┌─────────┐
                   │ repo_mgr   │                       │ e2b_runner   │  │ memory  │
                   │ (PyGithub) │                       │ (sandbox VM) │  │(Chroma) │
                   └─────┬──────┘                       └──────────────┘  └─────────┘
                         │ push branch + open PR after approval
                         ▼
                     ┌────────┐
                     │ GitHub │
                     └────────┘
```

## 4. Coding Rules (non-negotiable)

- Python 3.11+. `async def` everywhere I/O is involved.
- All secrets from `.env` via `python-dotenv`. Never hardcoded. Never logged.
- Every function has a one-line docstring stating purpose.
- Type hints on every parameter and return value.
- Every external API call wrapped in `try/except` with a logged, actionable message.
- No `print()`. Use `logging.getLogger(__name__)`.
- Max 40 lines per function. Split if longer.
- Every module under `bot/`, `agent/`, `github/`, `sandbox/`, `memory/` has a matching `tests/test_<module>.py`.
- Black-formatted, 100-char line limit.
- **Package management: `uv` only.** Never invoke `pip` or `python -m venv` directly. If `.venv/` is missing, run `uv venv --python 3.11`. Add deps with `uv add <pkg>` (dev: `uv add --group dev <pkg>`) and commit `uv.lock`. Run everything via `uv run <cmd>` — e.g. `uv run pytest`, `uv run python main.py`.

## 5. Phased Build Plan

### Phase 0 – Environment Setup
- **Goal:** Project skeleton + verified API connectivity.
- **Create:** `requirements.txt`, `.env`, `.env.example`, `config/settings.py`, `main.py` (stub), directory tree from spec.
- **Milestone:** `uv run python -c "from config.settings import get; print(get().verify())"` prints OK for Groq, Telegram, GitHub, E2B.
- **Test:** `uv run pytest tests/test_settings.py -v`

### Phase 1 – Telegram Skeleton
- **Goal:** Bot online, command routing works, no agent logic yet.
- **Create/Modify:** `bot/handler.py`, `bot/commands.py`, `bot/keyboards.py`, `main.py`.
- **Commands:** `/start`, `/repo <url>`, `/status`, `/history`, `/cancel`. Free text echoes back.
- **Milestone:** Send `/repo https://github.com/x/y` → bot replies "Repo set: x/y". `/status` returns "idle".
- **Test:** `pytest tests/test_bot.py -v` using PTB's `ApplicationBuilder` test harness.

### Phase 2 – GitHub Tools
- **Goal:** Standalone repo manipulation, no agent involved.
- **Create:** `github/repo_manager.py`, `github/pr_manager.py`.
- **Functions:** `clone_repo`, `list_files`, `read_file`, `create_branch`, `write_file`, `commit`, `push_branch`, `open_pr`.
- **Milestone:** Script creates branch `agent/test`, writes `HELLO.md`, pushes, opens PR against a test repo.
- **Test:** `pytest tests/test_repo_manager.py tests/test_pr_manager.py -v` (use a dedicated sandbox repo).

### Phase 3 – E2B Sandbox
- **Goal:** Run arbitrary repo's tests in isolated VM.
- **Create:** `sandbox/e2b_runner.py`.
- **Functions:** `start_sandbox`, `upload_repo`, `install_deps`, `run_pytest`, `shutdown`. Returns `{exit_code, stdout, stderr, duration_s}`.
- **Milestone:** Feed a small repo with one passing + one failing test; returns correct exit codes and captured output.
- **Test:** `pytest tests/test_e2b_runner.py -v -m integration`.

### Phase 4 – Agent Brain
- **Goal:** Full agentic loop wired end-to-end.
- **Create:** `agent/orchestrator.py`, `agent/tools.py`.
- **Implement:** Groq tool-calling loop per Section 7. Tools: `list_files`, `read_file`, `write_file`, `run_tests`, `task_complete`. Self-correction: max 3 retries on red tests. Checkpoint to `checkpoints/<task_id>.json` after every tool call. Reasoning toggle: classify task length/complexity; `reasoning_effort="none"` for ≤1 file edits, default otherwise.
- **Milestone:** Telegram task "add a function `add(a,b)` to utils.py with a pytest" runs end-to-end → green tests → approval prompt → PR opened.
- **Test:** `pytest tests/test_orchestrator.py -v` (mock Groq + E2B for unit; one live integration test).

### Phase 5 – Memory + Voice
- **Goal:** Persistent lessons, voice input, crash recovery.
- **Create:** `agent/memory.py`, `memory/store.py`. Modify: `bot/handler.py` (voice), `bot/commands.py` (`/resume`).
- **Memory:** ChromaDB collection per repo. After `task_complete`, agent writes a 1–3 sentence "lesson" embedded and stored. On task start, top-3 lessons retrieved and injected into system prompt.
- **Voice:** On Telegram voice note, download OGG → Groq Whisper → treat transcript as task message.
- **Resume:** `/resume <task_id>` loads latest checkpoint and continues loop.
- **Milestone:** Kill process mid-task; `/resume` finishes it. Voice note "list files in src" works.
- **Test:** `pytest tests/test_memory.py tests/test_voice.py -v`.

### Phase 6 – Polish + Deploy
- **Goal:** Production-ready on Railway.
- **Modify:** all modules — add retry decorators (`tenacity`) on Groq/GitHub/E2B calls (exp backoff, max 3). Add `Procfile`, `railway.toml`.
- **CI feedback:** GitHub Actions webhook on PR → Telegram message with run status.
- **Milestone:** Deployed on Railway, end-to-end task from phone completes; CI status pings Telegram.
- **Test:** `pytest tests/ -v --cov=. --cov-fail-under=70`.

## 6. File-by-File Responsibility Map

| File | Does | Must NOT |
|---|---|---|
| `main.py` | Entry point, wires bot + settings | Contain business logic |
| `config/settings.py` | Loads + validates `.env` | Contain runtime state |
| `bot/handler.py` | PTB `Application` setup, routes updates | Call GitHub/E2B directly |
| `bot/commands.py` | Command callbacks, calls orchestrator | Implement agent logic |
| `bot/keyboards.py` | Inline keyboards (approve/reject) | Hold state |
| `agent/orchestrator.py` | Agentic loop, Groq calls, checkpointing | Touch Telegram or GitHub APIs directly |
| `agent/tools.py` | Tool schemas + dispatch to managers | Contain LLM calls |
| `agent/memory.py` | Lesson save/retrieve via store | Embed Telegram concerns |
| `github/repo_manager.py` | Clone, read, write, branch, commit, push | Open PRs |
| `github/pr_manager.py` | Open/update PRs, post comments | Modify files |
| `sandbox/e2b_runner.py` | Sandbox lifecycle + pytest | Persist anything |
| `memory/store.py` | ChromaDB collection wrapper | Know about agents |
| `checkpoints/` | JSON snapshots of agent state | Be committed to git |

## 7. Agent Loop Specification

Implement in `agent/orchestrator.py` exactly:

```
async def run_task(task_id, repo, user_prompt):
    state = load_checkpoint(task_id) or new_state(task_id, repo, user_prompt)
    messages = state.messages or build_initial_messages(repo, user_prompt, recall_lessons(repo))
    retries = state.retries  # consecutive failed test runs
    effort = classify_effort(user_prompt)  # "none" | "default"

    while True:
        response = await groq.chat(
            model="qwen/qwen3-32b",
            messages=messages,
            tools=TOOL_SCHEMAS,
            reasoning_effort=effort,
        )
        messages.append(response.message)

        if not response.tool_calls:
            messages.append(system("You must call a tool or task_complete."))
            continue

        for call in response.tool_calls:
            result = await dispatch_tool(call, repo, sandbox)
            messages.append(tool_msg(call.id, result))
            state.messages = messages
            save_checkpoint(state)

            if call.name == "run_tests":
                if result.exit_code == 0:
                    retries = 0
                else:
                    retries += 1
                    if retries > 3:
                        return abort(task_id, "max retries exceeded")

            if call.name == "task_complete":
                approved = await request_telegram_approval(task_id, diff_summary())
                if not approved:
                    return abort(task_id, "user rejected")
                branch = await push_branch(repo, task_id)
                pr_url = await open_pr(repo, branch, result.summary)
                save_lesson(repo, result.lesson)
                clear_checkpoint(task_id)
                return pr_url
```

Rules: never mutate `messages` outside the loop; checkpoint after **every** tool result; `task_complete` is the only termination path besides abort.

## 8. Environment Variables

`.env.example`:

```
# Groq — https://console.groq.com/keys
GROQ_API_KEY=

# Telegram — @BotFather
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=123456789   # comma-separated, hard auth

# GitHub — https://github.com/settings/tokens (fine-grained, repo scope)
GITHUB_TOKEN=
GITHUB_DEFAULT_BRANCH=main

# E2B — https://e2b.dev/dashboard
E2B_API_KEY=

# Runtime
LOG_LEVEL=INFO
CHECKPOINT_DIR=./checkpoints
CHROMA_DIR=./chroma_data
MAX_TEST_RETRIES=3
```

`settings.py` must raise on startup if any non-runtime key is missing.

## 9. Test Strategy

| Module | Tests |
|---|---|
| `config/settings` | Missing key raises; values parsed correctly |
| `bot/*` | Command dispatch, user allowlist enforcement, keyboard callback parsing |
| `github/repo_manager` | Clone, read, write, branch creation against fixture repo |
| `github/pr_manager` | PR open returns URL, idempotent on retry |
| `sandbox/e2b_runner` | Pass-case + fail-case exit codes, timeout handling |
| `agent/orchestrator` | Tool dispatch, retry cap, checkpoint round-trip, approval gate |
| `agent/memory` | Save → retrieve top-k, repo isolation |

Run all: `pytest tests/ -v`. Coverage gates: Phase 2 ≥60%, Phase 4 ≥65%, Phase 6 ≥70%.

## 10. Do Not Do

- Never push directly to `main` or `GITHUB_DEFAULT_BRANCH`.
- Never hardcode API keys or tokens.
- Never run repo code outside the E2B sandbox.
- Never push a branch or open a PR before Telegram approval.
- Never use `print()`. Logging only.
- Never exceed 40 lines per function.
- Never serve users not in `TELEGRAM_ALLOWED_USER_IDS`.
- Never commit `checkpoints/`, `chroma_data/`, or `.env`.

## 11. Current Phase Tracker

Authoritative pointer: [docs/current-phase.md](../docs/current-phase.md). Update that file at the end of every phase; keep the snapshot below in sync.

```
Current Phase: Phase 2 — GitHub Tools
Last completed milestone: Phase 1 (PTB skeleton; /repo, /status, /history, /cancel, echo, allowlist; 24 tests green)
Next action: Build github/repo_manager.py, github/pr_manager.py, github/exceptions.py + tests per docs/current-phase.md.
```

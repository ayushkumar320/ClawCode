# Build Plan — Phase by Phase

Granular, step-by-step build doc. Each phase lists every file to create, what goes in it, what to verify, and what to commit before moving on.

---

## Phase 0 — Environment Setup

**Goal:** Project skeleton + verified API connectivity for all four services.

### Steps

1. **Create `requirements.txt`**
   - `python-telegram-bot==21.*`
   - `groq>=0.11.0`
   - `PyGithub>=2.3`
   - `GitPython>=3.1`
   - `e2b-code-interpreter>=1.0`
   - `chromadb>=0.5`
   - `sentence-transformers>=3.0`
   - `python-dotenv>=1.0`
   - `tenacity>=8.2`
   - `pytest>=8.0`
   - `pytest-asyncio>=0.23`
   - `pytest-cov>=5.0`

2. **Create `.env.example`** — all keys from CLAUDE.md Section 8, no values.

3. **Create `.env`** — local-only, filled with real keys.

4. **Update `.gitignore`** — ensure `.env`, `checkpoints/`, `chroma_data/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.coverage` are listed.

5. **Create `config/settings.py`**
   - `Settings` class (dataclass or pydantic-style) with all env vars typed
   - `load()` function — reads `.env`, raises `EnvironmentError` on missing required keys
   - `verify()` async function — pings Groq, Telegram, GitHub, E2B; returns `dict[str, bool]`
   - Singleton instance `settings` exported at module level

6. **Create `main.py` (stub)**
   - Imports `settings`, logs "ClawCode starting"
   - Calls `settings.verify()` and logs results
   - Exits — no bot logic yet

7. **Create `tests/test_settings.py`**
   - Test missing key raises `EnvironmentError`
   - Test all values parsed correctly with monkeypatched env
   - Test `TELEGRAM_ALLOWED_USER_IDS` parses comma-separated string to `list[int]`

### Verification
- `python main.py` prints OK for all 4 services
- `pytest tests/test_settings.py -v` — all green

### Commit
`chore: phase 0 — environment setup and API verification`

---

## Phase 1 — Telegram Skeleton

**Goal:** Bot online with command routing. No agent logic.

### Steps

1. **Create `bot/keyboards.py`**
   - `approval_keyboard(task_id: str) -> InlineKeyboardMarkup` — Approve / Reject buttons
   - Callback data format: `f"approve:{task_id}"` / `f"reject:{task_id}"`

2. **Create `bot/commands.py`**
   - `start_cmd(update, context)` — welcome message
   - `repo_cmd(update, context)` — parse URL, store `owner/name` in `context.user_data["repo"]`, reply "Repo set: x/y"
   - `status_cmd(update, context)` — return current task state (placeholder: "idle")
   - `history_cmd(update, context)` — list recent tasks (placeholder: "no history yet")
   - `cancel_cmd(update, context)` — clear current task (placeholder)
   - `echo_handler(update, context)` — for now, echo any free text back

3. **Create `bot/handler.py`**
   - `build_application() -> Application` — constructs PTB Application
   - Registers all commands from `commands.py`
   - Registers `MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler)`
   - **Auth middleware**: wraps every handler — checks `update.effective_user.id` against `settings.TELEGRAM_ALLOWED_USER_IDS`, rejects with "Unauthorized" if not in list

4. **Modify `main.py`**
   - Build application
   - Run polling: `app.run_polling()`

5. **Create `tests/test_bot.py`**
   - Test auth middleware blocks unauthorized user IDs
   - Test `/repo https://github.com/x/y` sets `user_data["repo"] = "x/y"` and replies correctly
   - Test `/status` returns "idle" when no task active
   - Test echo handler returns input text

### Verification
- Run `python main.py`, send `/start` from Telegram → welcome message
- `/repo https://github.com/octocat/Hello-World` → "Repo set: octocat/Hello-World"
- `/status` → "idle"
- Send from a non-allowed account → "Unauthorized"
- `pytest tests/test_bot.py -v` — all green

### Commit
`feat(bot): phase 1 — telegram skeleton with command routing and auth`

---

## Phase 2 — GitHub Tools

**Goal:** Standalone repo manipulation. Agent not involved.

### Steps

1. **Create `github/repo_manager.py`**
   - `clone_repo(repo_full_name: str, local_path: Path) -> Repo` — uses GitPython
   - `list_files(local_path: Path, ignore_globs: list[str] = None) -> list[str]` — respects `.gitignore`
   - `read_file(local_path: Path, file_path: str, start_line: int = None, end_line: int = None) -> str` — supports line ranges (see [improvements.md](improvements.md) #1, Layer 1)
   - `write_file(local_path: Path, file_path: str, content: str) -> None`
   - `create_branch(local_path: Path, branch_name: str) -> None`
   - `commit(local_path: Path, message: str, author: str = "ClawCode Agent") -> str` — returns commit SHA
   - `push_branch(local_path: Path, branch_name: str) -> None` — uses `GITHUB_TOKEN` for auth
   - **Hard rule:** raise if `branch_name == settings.GITHUB_DEFAULT_BRANCH`

2. **Create `github/pr_manager.py`**
   - Uses `PyGithub`
   - `open_pr(repo_full_name: str, head_branch: str, base_branch: str, title: str, body: str) -> str` — returns PR URL
   - `comment_on_pr(repo_full_name: str, pr_number: int, body: str) -> None`
   - Idempotent: if a PR already exists for `head_branch`, return its URL instead of erroring

3. **Create a dedicated sandbox GitHub repo** for testing (e.g., `your-username/clawcode-sandbox`)

4. **Create `tests/test_repo_manager.py`**
   - Test clone, read, write, branch creation against the sandbox repo
   - Test `read_file` with line ranges returns correct slice
   - Test `read_file` with no range and large file returns truncated output with note
   - Test push to `main` raises

5. **Create `tests/test_pr_manager.py`**
   - Test open PR returns valid URL
   - Test reopening same head branch returns existing PR URL (idempotency)
   - Mark these as `@pytest.mark.integration` — they hit real GitHub

### Verification
- Manual script: clone sandbox repo, create branch `agent/test-phase2`, write `HELLO.md`, push, open PR → PR visible on GitHub
- `pytest tests/test_repo_manager.py tests/test_pr_manager.py -v -m integration` — all green
- Coverage: ≥60%

### Commit
`feat(github): phase 2 — repo and PR managers with line-range reads`

---

## Phase 3 — E2B Sandbox

**Goal:** Run any repo's tests inside an isolated VM.

### Steps

1. **Create `sandbox/e2b_runner.py`**
   - `class E2BRunner` with async methods:
     - `start() -> None` — spawns sandbox
     - `upload_repo(local_path: Path) -> None` — uploads files to sandbox `/repo/`
     - `install_deps() -> dict` — runs `pip install -r requirements.txt` if present, returns `{exit_code, stdout, stderr}`
     - `run_pytest(args: list[str] = None, timeout_s: int = 120) -> dict` — returns `{exit_code, stdout, stderr, duration_s}`
     - `run_command(cmd: str, timeout_s: int = 60) -> dict` — generic command runner
     - `shutdown() -> None` — kills sandbox
   - Truncate any stdout/stderr exceeding 4k tokens with a note (see [improvements.md](improvements.md) #1, Layer 2)
   - Wrap E2B calls with `tenacity` retry: max 2 retries, exponential backoff

2. **Create `tests/test_e2b_runner.py`**
   - Create a tiny fixture repo with one passing + one failing test
   - Test `run_pytest` returns exit code 1 with both pass and fail in output
   - Test timeout enforcement (run a sleep command exceeding limit)
   - Test truncation: produce 10k-token output, verify it's clipped with note
   - Mark as `@pytest.mark.integration`

### Verification
- Manual test: upload a known-good Python project, run pytest, see green
- Manual test: upload a known-broken project, run pytest, see exit code != 0
- `pytest tests/test_e2b_runner.py -v -m integration` — all green

### Commit
`feat(sandbox): phase 3 — e2b runner with test execution and output truncation`

---

## Phase 4 — Agent Brain

**Goal:** Full agentic loop end-to-end. This is the core phase.

### Steps

1. **Create `agent/tools.py`**
   - Define `TOOL_SCHEMAS` — Groq-compatible JSON schemas for:
     - `list_files(path: str = ".")` — returns repo file tree
     - `read_file(path: str, start_line: int = None, end_line: int = None)` — supports ranges
     - `write_file(path: str, content: str)`
     - `run_tests(args: list[str] = None)`
     - `task_complete(summary: str, lesson: str)` — terminates the loop
   - `dispatch_tool(call, repo_path, sandbox) -> dict` — async dispatcher
   - **Truncation wrapper**: every dispatched tool's result passes through `truncate_to_tokens(result, max=4000)` before returning

2. **Create `agent/orchestrator.py`**
   - `classify_effort(prompt: str) -> str` — heuristic: short prompts ≤80 chars + single file mention → `"none"`, else `"default"`
   - `build_initial_messages(repo, user_prompt, lessons) -> list[dict]` — system prompt + user prompt
   - `trim_context(messages, max_tokens=25000) -> list[dict]` — see [improvements.md](improvements.md) #1, Layer 3 (sliding window summarization)
   - `save_checkpoint(state)` / `load_checkpoint(task_id)` — JSON to `checkpoints/<task_id>.json`
   - `clear_checkpoint(task_id)` — on success
   - `run_task(task_id, repo, user_prompt, status_callback)` — implements the loop from CLAUDE.md Section 7 exactly
   - **Status callback**: emit progress messages at: task start, each tool call, test result, approval request, completion (see [improvements.md](improvements.md) #2)
   - **Timeline logging**: append structured event to `state.timeline` after each tool dispatch (see [improvements.md](improvements.md) #4)

3. **Modify `bot/commands.py`**
   - Add `task_handler(update, context)` — triggered by any non-command text after a repo is set
   - Calls `orchestrator.run_task(...)`, passes a `status_callback` that sends messages to the Telegram chat
   - On `task_complete` from orchestrator, sends approval keyboard, awaits callback
   - Implement callback query handler for `approve:` / `reject:` patterns

4. **Modify `bot/handler.py`** — register the callback query handler

5. **Create `tests/test_orchestrator.py`**
   - Test `classify_effort` returns correct level for various prompts
   - Test `trim_context` reduces message count when exceeding limit
   - Test checkpoint round-trip — save state, load, verify equality
   - Test retry cap — mock failing tests 4x, assert abort on 4th
   - Test `task_complete` requires approval before any push/PR action
   - One integration test: real Groq + mocked E2B + mocked GitHub — assert tools dispatch in expected order

### Verification
- End-to-end: from Telegram, send `/repo https://github.com/your/sandbox`, then send "Add a function add(a,b) to utils.py with a pytest"
- Observe status messages flowing to Telegram during execution
- Approval keyboard appears → tap Approve → PR opens
- `pytest tests/test_orchestrator.py -v` — all green
- Coverage: ≥65%

### Commit
`feat(agent): phase 4 — agentic loop with checkpointing, context trimming, and approval gate`

---

## Phase 5 — Memory + Voice

**Goal:** Persistent lessons, voice input, crash recovery.

### Steps

1. **Create `memory/store.py`**
   - `class MemoryStore` wrapping ChromaDB
   - `save_lesson(repo: str, lesson: str) -> None` — embeds with `all-MiniLM-L6-v2`, stores in collection named after repo
   - `recall(repo: str, query: str, top_k: int = 3) -> list[str]` — semantic search
   - Collection-per-repo for isolation

2. **Create `agent/memory.py`**
   - Thin wrapper around `memory/store.py`
   - `recall_lessons(repo: str, user_prompt: str) -> list[str]`
   - `save_lesson(repo: str, lesson: str) -> None`
   - Used by orchestrator at task start (inject into system prompt) and on `task_complete`

3. **Modify `bot/handler.py`**
   - Add `MessageHandler(filters.VOICE, voice_handler)`

4. **Create voice handler in `bot/commands.py`**
   - `voice_handler(update, context)`:
     - Download OGG file
     - Send to Groq Whisper (`whisper-large-v3-turbo`)
     - Pass transcript to `task_handler` as if user had typed it
     - Confirm transcription in chat: "Heard: <transcript>"

5. **Add `/resume` command to `bot/commands.py`**
   - `resume_cmd(update, context, task_id: str)` — load checkpoint, continue loop

6. **Create `tests/test_memory.py`**
   - Test save → recall returns the saved lesson
   - Test repo isolation: lesson saved for repo A not returned for repo B
   - Test top-k ordering by semantic similarity

7. **Create `tests/test_voice.py`**
   - Mock Whisper response, verify transcript is dispatched to task handler

### Verification
- Kill the bot mid-task (Ctrl+C during a long task) → restart → `/resume <task_id>` → completes
- Send voice note "list files in src" → bot transcribes and acts
- After a task, send a similar task to the same repo → confirm lesson appears in agent's context (log it)
- `pytest tests/test_memory.py tests/test_voice.py -v` — all green

### Commit
`feat: phase 5 — chromadb-backed memory, voice input, and task resume`

---

## Phase 6 — Polish + Deploy

**Goal:** Production-ready on Railway.

### Steps

1. **Add `tenacity` retries everywhere external APIs are called**
   - Groq: exponential backoff, max 3, retry on 429/500/503
   - GitHub: exponential backoff, max 3, retry on 403/500/502
   - E2B: already added in Phase 3

2. **Create `Procfile`**
   - `worker: python main.py`

3. **Create `railway.toml`**
   - Build/start commands, environment variable references

4. **Add GitHub Actions webhook receiver**
   - New file `bot/webhook.py` — FastAPI or aiohttp endpoint
   - Receives `workflow_run` events
   - Matches PR to task, sends CI status to the originating Telegram chat
   - Modify `main.py` to run both polling and webhook server concurrently

5. **Add structured logging**
   - JSON formatter for production logs
   - Log task timeline events as structured records

6. **Deploy to Railway**
   - Set env vars in Railway dashboard
   - Configure webhook URL in GitHub repo settings
   - Run end-to-end test from phone

7. **Final test pass**
   - `pytest tests/ -v --cov=. --cov-fail-under=70`

### Verification
- Deployed bot responds from phone
- End-to-end task: send prompt → PR opens → CI runs → Telegram pings with status
- Coverage ≥70%

### Commit
`chore: phase 6 — production deploy with retries, webhooks, and structured logs`

---

## Order of Operations Summary

| Phase | Touches | Blockers Before Next Phase |
|---|---|---|
| 0 | Config, env | All 4 API keys must verify |
| 1 | Bot routing | Auth middleware must reject non-allowed users |
| 2 | GitHub I/O | Cannot push to main; PR opens cleanly |
| 3 | Sandbox | Pytest run returns correct exit codes |
| 4 | Agent loop | End-to-end task completes with approval gate |
| 5 | Memory + voice | Resume from checkpoint works |
| 6 | Deploy | Live on Railway, CI feedback wired |

## Cross-Phase Concerns

- **Context window** ([improvements.md](improvements.md) #1) — Layer 1 lands in Phase 2 (line-range reads), Layer 2 in Phase 3 (truncation in sandbox) and Phase 4 (truncation in tool dispatch), Layer 3 in Phase 4 (trim_context)
- **Progress feedback** ([improvements.md](improvements.md) #2) — implemented in Phase 4 via status callbacks
- **Timeline logging** ([improvements.md](improvements.md) #4) — implemented in Phase 4 alongside checkpointing
- **Retries** ([improvements.md](improvements.md) #5) — added per-phase as each external API is introduced (Phase 3 for E2B, Phase 4 for Groq, Phase 6 audits all)

# Current Phase

> Single source of truth for what we are building **right now**. Update this file at the end of every phase. Keep CLAUDE.md §11 in sync.

---

## Now building: Phase 4 — Agent Brain

**Goal:** End-to-end agentic loop: Groq tool-calling, tool dispatch to gh + sandbox, checkpointing, self-correction on red tests, Telegram approval gate before PR.

**Create / modify**
- `agent/exceptions.py` — `AgentError`, `MaxRetriesExceeded`, `UserRejected`.
- `agent/state.py` — frozen-ish `AgentState` model (pydantic): `task_id`, `repo_slug`, `user_prompt`, `messages: list[dict]`, `retries: int`, `version: int = 1`. JSON round-trip.
- `agent/checkpoints.py` — `save(state)`, `load(task_id) -> AgentState | None`, `clear(task_id)`. Writes atomically (temp file + rename) under `settings.checkpoint_dir`.
- `agent/tools.py` — JSON-schema tool definitions for `list_files`, `read_file`, `write_file`, `run_tests`, `task_complete`. Dispatch table mapping tool name → async callable. Argument validation against schema before dispatch (LLM output untrusted).
- `agent/orchestrator.py` — `run_task(task_id, repo_slug, user_prompt, approval_cb)` implementing the loop from CLAUDE.md §7 exactly. Effort classifier helper (`classify_effort` → `"none"` for ≤1 file edits). Bounded retries (3) on red `run_tests`.
- `tests/test_state.py`, `tests/test_checkpoints.py`, `tests/test_tools.py`, `tests/test_orchestrator.py` — Groq + sandbox + gh all mocked. One `@pytest.mark.integration` end-to-end skipped without `RUN_INTEGRATION=1`.

**Out of scope (do NOT touch yet)**
- Memory / ChromaDB lessons — Phase 5.
- Voice transcription — Phase 5.
- Live deploy / tenacity retries on every external call — Phase 6 (but `run_task`'s 3-retry self-correction loop is in scope).

**Hard guards (encode in code, not just comments)**
- Tool arguments validated against the schema before dispatch; reject unknown tools.
- `run_tests` failures increment `retries`; `retries > MAX_TEST_RETRIES` → abort with `MaxRetriesExceeded`.
- `task_complete` is the *only* successful termination path; nothing else may push or open a PR.
- PR opens **only** after `approval_cb` returns `True`.
- Checkpoint written after **every** tool result (atomic temp-file rename).
- No direct GitHub / Telegram / Groq calls inside `agent/tools.py` (LLM-free) or `agent/orchestrator.py` (Telegram-free).
- `agent/` never logs `user_prompt` or tool args at INFO+ (treat as user data).

**Milestone**
- Unit: a synthetic Groq stub drives the loop through `list_files` → `read_file` → `write_file` → `run_tests` (green) → `task_complete`; with `approval_cb=lambda: True` and mocked `push_branch` / `open_pr`, the loop returns a fake PR URL and clears the checkpoint.
- Red-test retry: stub returns `exit_code=1` three times → loop aborts with `MaxRetriesExceeded`.
- Rejection: `approval_cb=lambda: False` → no push, returns rejected status.

**Tests**
- `uv run pytest tests/test_state.py tests/test_checkpoints.py tests/test_tools.py tests/test_orchestrator.py -v`
- Tool-schema validation (good + malformed args).
- Checkpoint round-trip: save → load → equal. Atomic write survives interrupted rename.
- Orchestrator branches: success, max-retries, user-reject, unknown tool.

**Definition of done**
- All prior tests still pass.
- New tests pass.
- `uv run ruff check .` and `uv run black --check .` clean.
- Coverage ≥ 65% overall (Phase 4 gate).
- This file updated to point at Phase 5.
- `.claude/CLAUDE.md` §11 snapshot updated.

---

## Setup reminder (every fresh checkout)

```bash
uv venv --python 3.11   # only if .venv/ is missing
uv sync --all-groups
cp .env.example .env    # then fill in real values
uv run python main.py
```

---

## Phase ledger

| Phase | Status | Notes |
|---|---|---|
| 0 — Environment Setup | ✅ done | Settings, .env.example, uv, CI, test_settings green |
| 1 — Telegram Skeleton | ✅ done | handler/commands/keyboards + 24 bot tests green |
| 2 — GitHub Tools | ✅ done | gh/{repo_manager,pr_manager,exceptions}; 19 new tests; 93% coverage |
| 3 — E2B Sandbox | ✅ done | sandbox/{e2b_runner,exceptions}; RunResult, timeout, scrub, truncate, idempotent shutdown; 18 new tests; 95% coverage |
| 4 — Agent Brain | 🔨 **in progress** | this doc |
| 5 — Memory + Voice | ⏳ | |
| 6 — Polish + Deploy | ⏳ | Railway, tenacity, CI→Telegram |

Full phase details: [build-plan.md](build-plan.md) and CLAUDE.md §5.

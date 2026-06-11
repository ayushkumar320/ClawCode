# Current Phase

> Single source of truth for what we are building **right now**. Update this file at the end of every phase. Keep CLAUDE.md §11 in sync.

---

## Now building: Phase 5 — Memory + Voice

**Goal:** Persistent per-repo lessons, voice-note task input, crash-safe resume.

**Create / modify**
- `memory/store.py` — ChromaDB-backed collection wrapper. Methods: `add_lesson(repo_slug, text)`, `top_k(repo_slug, query, k=3)`. Collection name derived from `repo_slug`, isolated per repo.
- `agent/memory.py` — orchestrator-facing helpers: `recall_lessons(repo_slug) -> str` (formatted block ready for system prompt) and `save_lesson(repo_slug, lesson)`. Caps lesson length and strips control characters (rule §5.8 — lessons are untrusted input).
- `agent/orchestrator.py` — inject lessons into `build_initial_messages` (system prompt addition); call `save_lesson` from `_finalize` after a successful PR.
- `bot/voice.py` — download a Telegram voice OGG, transcribe via Groq Whisper (`whisper-large-v3-turbo`), return text. Treat transcript as the user task message.
- `bot/handler.py` + `bot/commands.py` — route voice messages through `bot.voice` and into the agent dispatch path; add `/resume <task_id>` that loads the latest checkpoint and continues.
- Tests: `tests/test_memory_store.py`, `tests/test_agent_memory.py`, `tests/test_voice.py`, and resume coverage in `tests/test_orchestrator.py`.

**Out of scope (do NOT touch yet)**
- Railway deploy / Procfile / tenacity wrappers — Phase 6.
- CI→Telegram bridge — Phase 6.

**Hard guards**
- Lessons capped at e.g. 512 chars, control chars stripped, wrapped in `<lesson>...</lesson>` tags inside the system prompt so the model treats them as untrusted context.
- ChromaDB collection name uses `repo_slug` only (sanitized); never write a lesson with empty text.
- Voice download has a timeout and a max file size; transcription call has its own timeout.
- Never log voice content at INFO+ — it's user input.
- Embeddings model loaded once at process start (memoized inside `memory/store.py`), never per-request.

**Milestone**
- Send a voice note "list files in src" → transcribed → echoed as a normal task message.
- Run a task end-to-end, get PR, restart process, send another task → top-3 prior lessons appear in the system prompt of the second task.
- Kill mid-task → `/resume <task_id>` finishes from the last checkpoint.

**Tests**
- `uv run pytest tests/test_memory_store.py tests/test_agent_memory.py tests/test_voice.py -v`
- Round-trip: `add_lesson` → `top_k` returns it for similar query.
- Per-repo isolation: lessons saved under `a/x` not visible from `b/y`.
- Voice: Telegram file download mocked, Groq Whisper mocked; happy path returns transcript; timeout path raises typed error.
- Orchestrator: lessons injected into initial messages; `save_lesson` invoked post-PR.

**Definition of done**
- All prior tests still pass.
- New tests pass.
- `uv run ruff check .` and `uv run black --check .` clean.
- Coverage ≥ 65% overall.
- This file updated to point at Phase 6.
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
| 4 — Agent Brain | ✅ done | agent/{exceptions,state,checkpoints,tools,llm,orchestrator}; loop with retries, approval gate, atomic checkpoints; 33 new tests; 96% coverage |
| 5 — Memory + Voice | 🔨 **in progress** | this doc |
| 6 — Polish + Deploy | ⏳ | Railway, tenacity, CI→Telegram |

Full phase details: [build-plan.md](build-plan.md) and CLAUDE.md §5.

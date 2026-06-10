# Current Phase

> Single source of truth for what we are building **right now**. Update this file at the end of every phase. Keep CLAUDE.md §11 in sync.

---

## Now building: Phase 1 — Telegram Skeleton

**Goal:** Bot online, command routing works, no agent logic yet.

**Create / modify**
- `bot/handler.py` — PTB `Application` setup, update routing, user allowlist enforcement.
- `bot/commands.py` — command callbacks (`/start`, `/repo <url>`, `/status`, `/history`, `/cancel`); free text echoes back.
- `bot/keyboards.py` — inline keyboards (stub; real approve/reject lands Phase 4).
- `main.py` — wire `bot.handler` into the entry point after `Settings` loads.
- `tests/test_bot.py` — PTB test harness coverage of command dispatch + allowlist.

**Out of scope (do NOT touch yet)**
- GitHub API, E2B sandbox, Groq calls, ChromaDB, voice. Those are Phases 2–5.
- Real PR/approval flow — keyboards are stubs.

**Milestone**
- `uv run python main.py` starts the bot in long-polling mode.
- Sending `/repo https://github.com/x/y` → bot replies `Repo set: x/y` (held in in-memory per-user state, not persisted yet).
- `/status` returns `idle`.
- Non-allowlisted user IDs are silently dropped (logged at INFO).

**Tests**
- `uv run pytest tests/test_bot.py -v`
- Must cover: command dispatch, allowlist enforcement (allowed + denied), `/repo` URL parsing (valid + malformed), keyboard callback parsing stub.

**Definition of done**
- All Phase 0 tests still pass.
- New tests pass.
- `uv run ruff check .` and `uv run black --check .` clean.
- This file updated to point at Phase 2.
- CLAUDE.md §11 updated: `Current Phase: Phase 1` → `Phase 2`, milestone recorded.

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
| 1 — Telegram Skeleton | 🔨 **in progress** | this doc |
| 2 — GitHub Tools | ⏳ next | |
| 3 — E2B Sandbox | ⏳ | |
| 4 — Agent Brain | ⏳ | |
| 5 — Memory + Voice | ⏳ | |
| 6 — Polish + Deploy | ⏳ | Railway, tenacity, CI→Telegram |

Full phase details: [build-plan.md](build-plan.md) and CLAUDE.md §5.

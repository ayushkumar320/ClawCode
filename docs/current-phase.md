# Current Phase

> Single source of truth for what we are building **right now**. Update this file at the end of every phase. Keep CLAUDE.md §11 in sync.

---

## Now building: Phase 2 — GitHub Tools

**Goal:** Standalone repo manipulation — clone, read, write, branch, commit, push, open PR — no agent involved.

**Create / modify**
- `github/repo_manager.py` — `clone_repo`, `list_files`, `read_file`, `create_branch`, `write_file`, `commit`, `push_branch`. Local Git ops via `GitPython`; remote auth via `GITHUB_TOKEN`.
- `github/pr_manager.py` — `open_pr` (idempotent: if a PR with the same head branch is already open, return its URL). Uses `PyGithub`.
- `github/exceptions.py` — `RepoError`, `PRError` typed exceptions.
- `tests/test_repo_manager.py`, `tests/test_pr_manager.py` — unit tests against a temp `git init --bare` upstream + temp working clone. Integration test against a real sandbox repo is `@pytest.mark.integration`.

**Out of scope (do NOT touch yet)**
- Bot/agent wiring of these tools — Phase 4 hooks them in.
- E2B sandbox, ChromaDB, Groq.
- Direct file writes from agent logic.

**Hard guards (encode in code, not just comments)**
- `create_branch` must reject `main` and `GITHUB_DEFAULT_BRANCH`.
- `push_branch` must refuse to push to a protected branch name.
- Never log `GITHUB_TOKEN`. Inject via remote URL rewrite; scrub from error messages.

**Milestone**
- A script (or test) creates branch `agent/test`, writes `HELLO.md`, commits, pushes, opens a PR against a designated sandbox repo, returns the PR URL. Re-running is idempotent (no duplicate PR).

**Tests**
- `uv run pytest tests/test_repo_manager.py tests/test_pr_manager.py -v`
- Unit coverage: clone, list/read/write, branch creation (including reject-protected), commit author/email, idempotent PR.
- Integration test marked `@pytest.mark.integration`, skipped unless `RUN_INTEGRATION=1`.

**Definition of done**
- All prior tests still pass.
- New tests pass.
- `uv run ruff check .` and `uv run black --check .` clean.
- Coverage ≥ 60% (Phase 2 gate from CLAUDE.md §9).
- This file updated to point at Phase 3.
- CLAUDE.md §11 snapshot updated.

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
| 2 — GitHub Tools | 🔨 **in progress** | this doc |
| 3 — E2B Sandbox | ⏳ | |
| 4 — Agent Brain | ⏳ | |
| 5 — Memory + Voice | ⏳ | |
| 6 — Polish + Deploy | ⏳ | Railway, tenacity, CI→Telegram |

Full phase details: [build-plan.md](build-plan.md) and CLAUDE.md §5.

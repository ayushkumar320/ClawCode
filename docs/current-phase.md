# Current Phase

> Single source of truth for what we are building **right now**. Update this file at the end of every phase. Keep CLAUDE.md §11 in sync.

---

## Now building: Phase 3 — E2B Sandbox

**Goal:** Run an arbitrary repo's tests inside an isolated Firecracker microVM and capture results.

**Create / modify**
- `sandbox/e2b_runner.py` — async wrapper around `e2b-code-interpreter`. Functions: `start_sandbox`, `upload_repo`, `install_deps`, `run_pytest`, `shutdown`.
- `sandbox/exceptions.py` — `SandboxError` typed exception.
- `sandbox/result.py` (or top of `e2b_runner.py`) — `RunResult` frozen dataclass with `exit_code: int`, `stdout: str`, `stderr: str`, `duration_s: float`.
- `tests/test_e2b_runner.py` — unit tests with the E2B SDK mocked (no real VM); one `@pytest.mark.integration` end-to-end test gated on `RUN_INTEGRATION=1` + a real `E2B_API_KEY`.

**Out of scope (do NOT touch yet)**
- Agent orchestration / Groq calls — Phase 4.
- Persisting sandbox state between tasks. Sandboxes are single-use per task.

**Hard guards (encode in code, not just comments)**
- Every sandbox call has a timeout. `run_pytest` accepts `timeout_s` and force-kills on overrun.
- `shutdown` is idempotent and always runs (use `async with` / `try/finally`).
- Never log `E2B_API_KEY`; scrub from error messages exactly like `repo_manager._scrub`.
- `RunResult.stdout` / `stderr` capped at e.g. 256 KiB — truncate with a `[...truncated]` marker. Keeps prompts and logs bounded.
- No network egress from `run_pytest` unless explicitly required by the test config.

**Milestone**
- Feed a tiny synthetic repo (one passing test + one failing test) → `run_pytest` returns `exit_code=1`, with both test names visible in `stdout`. Then a green-only variant returns `exit_code=0`.

**Tests**
- `uv run pytest tests/test_e2b_runner.py -v`
- Unit coverage (no network): sandbox lifecycle ordering, upload-then-install-then-run sequence, timeout path, stdout truncation, secret scrubbing on error.
- Integration: `@pytest.mark.integration` test asserting real pass/fail exit codes against a fixture repo.

**Definition of done**
- All prior tests still pass.
- New tests pass.
- `uv run ruff check .` and `uv run black --check .` clean.
- Coverage stays ≥ 60% overall.
- This file updated to point at Phase 4.
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
| 3 — E2B Sandbox | 🔨 **in progress** | this doc |
| 4 — Agent Brain | ⏳ | |
| 5 — Memory + Voice | ⏳ | |
| 6 — Polish + Deploy | ⏳ | Railway, tenacity, CI→Telegram |

Full phase details: [build-plan.md](build-plan.md) and CLAUDE.md §5.

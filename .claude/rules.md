# ClawCode — Strict Rules

> Non-negotiable. If a rule conflicts with a quick fix, the rule wins. If a rule conflicts with `CLAUDE.md`, `CLAUDE.md` wins.

---

## 1. Toolchain

1. **`uv` is the only package manager.** No `pip`, no `python -m venv`, no `poetry`, no `conda`.
2. If `.venv/` is missing: `uv venv --python 3.11 && uv sync --all-groups`. Never improvise.
3. Add deps with `uv add <pkg>` (dev: `uv add --group dev <pkg>`). Commit `uv.lock` every time it changes.
4. Run everything through `uv run` — `uv run pytest`, `uv run python main.py`, `uv run ruff check .`.
5. Python ≥ 3.11. No compatibility shims for older versions.

## 2. Code Quality (hard limits)

1. **Type hints on every parameter and return value.** No `Any` unless justified in a comment on the same line.
2. **One-line docstring on every function, class, and module.** State purpose, not mechanics.
3. **Max 40 lines per function.** Split if longer. Counted from `def` to last line of body, excluding docstring.
4. **Max 400 lines per file.** Split into submodules.
5. **Black-formatted, 100-char line limit.** `uv run black --check .` must pass.
6. **Ruff clean.** Rules `E, F, I, B, UP` selected. No `# noqa` without a comment explaining why on the same line.
7. **No `print()`.** Use `logging.getLogger(__name__)`. Module-level logger, never per-call.
8. **No bare `except:`.** Catch the narrowest exception that can actually be raised.
9. **No mutable default arguments.** Use `None` and assign inside the body.
10. **No global state.** Pass dependencies explicitly. The only acceptable singleton is `config.settings.get()`.
11. **No commented-out code.** Delete it; git remembers.
12. **No TODOs without an owner + date.** Format: `# TODO(ayush, 2026-06-11): …`. Untagged TODOs fail review.

## 3. Async & I/O

1. **Every I/O call is `async`.** Network, disk, subprocess. If a lib is sync-only, wrap with `asyncio.to_thread`.
2. **Never call `asyncio.run()` outside `main.py`.** Tests use `pytest-asyncio` auto mode.
3. **No blocking calls inside `async def`.** No `time.sleep`, no `requests.get`, no `open(...).read()` on hot paths.
4. **Every external API call has a timeout.** No unbounded `await`.
5. **Every external API call is wrapped in `try/except` with a logged, actionable message.** Include the operation name and any safe identifiers; never log secrets.
6. **Retries via `tenacity` only.** Exponential backoff, `max_attempts=3`, no infinite loops.

## 4. Errors

1. **Fail loud at boundaries, fail safe internally.** Bot handlers convert exceptions to user-visible messages; everything below raises typed exceptions.
2. **Define a typed exception per module** (`SettingsError`, `RepoError`, `SandboxError`, …). No raising bare `Exception` or `RuntimeError` except in tests.
3. **Never `except` and swallow.** Log + re-raise, or convert to a typed exception.
4. **Never use exceptions for control flow.**

## 5. Security

1. **All secrets via `.env` → `config.settings`.** Never hardcoded. Never logged. Never in error messages.
2. **Never log raw user input verbatim at INFO+.** DEBUG only, and only if it can't contain secrets.
3. **`TELEGRAM_ALLOWED_USER_IDS` is the only auth gate.** Enforce in `bot/handler.py` before any dispatch.
4. **Never run untrusted repo code outside the E2B sandbox.** No `subprocess.run` on cloned code, ever.
5. **Never push to `main` or `GITHUB_DEFAULT_BRANCH`.** Guard in `github/repo_manager.create_branch`.
6. **Never push a branch or open a PR before Telegram approval.** The only path is through `request_telegram_approval`.
7. **Treat LLM output as untrusted.** Validate tool-call arguments against schemas before dispatch. No `eval`, no `exec`, no shell-string interpolation of model output.
8. **Treat retrieved memory/lessons as untrusted.** Cap length, strip control characters, tag as `<lesson>` in prompts.

## 6. Testing

1. **Every module under `bot/`, `agent/`, `github/`, `sandbox/`, `memory/` has `tests/test_<module>.py`.** No exceptions.
2. **A change without a test is incomplete.** New behavior → new test. Bug fix → regression test that fails before the fix.
3. **Tests must be deterministic.** No `time.sleep`, no real network, no real LLM calls in unit tests. Use fakes/mocks.
4. **Integration tests live under `tests/integration/` and are marked `@pytest.mark.integration`.** Excluded from default `uv run pytest`.
5. **Coverage gates (enforced in CI):** Phase 2 ≥60%, Phase 4 ≥65%, Phase 6 ≥70%. Never lower a gate; only raise.
6. **No test reads from `.env`.** Use `monkeypatch.setenv`.

## 7. Git & PRs

1. **Branch naming:** `agent/<task_id>` for agent-generated, `feat/<slug>` / `fix/<slug>` / `chore/<slug>` for humans.
2. **One logical change per PR.** Refactors don't ride along with features.
3. **Commit messages: imperative, ≤72-char subject, body explains *why*.** Not what — the diff shows what.
4. **Never amend pushed commits. Never force-push shared branches.** New commit only.
5. **Never commit:** `.env`, `checkpoints/*` (except `.gitkeep`), `chroma_data/`, `.venv/`, secrets in any form.
6. **`uv.lock` is committed.** Dependency drift between machines is a bug.
7. **CI must be green before merge.** No `--no-verify`. No skipping hooks.

## 8. Architecture Boundaries

The dependency graph is directed; violations fail review.

```
main → bot → agent → {github, sandbox, memory}
                  ↓
              config.settings
```

1. `bot/` never imports from `github/`, `sandbox/`, or `memory/` directly. It goes through `agent/`.
2. `agent/orchestrator.py` never touches Telegram or GitHub APIs directly. It calls `agent/tools.py`.
3. `agent/tools.py` contains no LLM calls.
4. `memory/store.py` knows nothing about agents.
5. `config/settings.py` has no runtime state and no I/O beyond `dotenv.load_dotenv`.

## 9. Process

1. **Read [docs/current-phase.md](../docs/current-phase.md) before starting any task.** Do not work outside the current phase's scope.
2. **One phase at a time.** Finish + update the phase doc before opening the next.
3. **Definition of done for any change:**
   - Behavior implemented.
   - Test added and passing.
   - `uv run ruff check .` clean.
   - `uv run black --check .` clean.
   - `uv run pytest -v` green.
   - Phase doc + CLAUDE.md §11 updated if a milestone was hit.
4. **Don't add features the task doesn't require.** No speculative abstractions, no "while I'm here" cleanups.
5. **Don't add error handling for impossible states.** Validate at boundaries only.
6. **Don't write comments that restate the code.** Comments explain *why*, never *what*.

## 10. Hard "No"s

- No `print`. No `os.system`. No `eval`/`exec`. No `pickle` for anything that crosses a trust boundary.
- No mocking the LLM in integration tests labeled as end-to-end.
- No silently catching `BaseException` / `Exception`.
- No `requirements.txt`, no `setup.py`, no `Pipfile`. `pyproject.toml` + `uv.lock` only.
- No global mutable state, including module-level singletons not justified by `config.settings`.
- No "temporary" hacks without a `# TODO(owner, date)` and a tracked issue.

# Current Phase

> Single source of truth for what we are building **right now**. Update this file at the end of every phase. Keep CLAUDE.md §11 in sync.

---

## Now building: Maintenance / iteration

All six planned phases are done. The bot wires end-to-end locally; deployment
to Railway is a one-step operation (push to a connected repo, set the env
vars from [.env.example](../.env.example) under Railway → Variables, done).

**Open follow-ups (none blocking):**
- Replace the in-graph `MemorySaver` with a JSON-backed `BaseCheckpointSaver`
  so LangGraph natively resumes mid-tool-call instead of the bot dispatching
  a fresh run with saved messages. The protocol is non-trivial (channel
  versions, pending writes). Track as `# TODO(ayush, 2026-06-12)`.
- Verify Railway deploy + live PR end-to-end once the operator's GitHub
  fine-grained token is provisioned.
- Wire a `LANGCHAIN_PROJECT` env into the Studio launch command so traces
  group sensibly across local + Railway runs.

Phase doc is no longer "in progress" — leave this file pointing at
maintenance work until the next major scope lands.

### Previously: Phase 6 — Polish + Deploy

**Goal:** Production-ready: tenacity-wrapped external calls, Railway deploy, GitHub Actions → Telegram bridge, end-to-end wiring in `main.py` (orchestrator deps composed from real `LessonStore`, `transcribe_voice`, gh + sandbox callables).

**Create / modify**
- `main.py` — compose `OrchestratorDeps`: real `setup`/`teardown` (clone + start sandbox + upload), real `publish` (push + open_pr), real `approval` (Telegram inline keyboard wait), `recall_lessons` / `save_lesson` bound to `memory.store.LessonStore`. Register `transcribe_voice` + a `resume_task` callable into `application.bot_data`.
- `agent/checkpoint_saver.py` — JSON-backed `BaseCheckpointSaver` wrapping `agent/checkpoints.py` so the LangGraph picks up `/resume` natively. Replaces `MemorySaver` in `agent/orchestrator._build_graph`.
- Add tenacity retry decorators to Groq (`agent/llm.py`), GitHub (`gh/repo_manager.push_branch`, `gh/pr_manager.open_pr`), E2B (`sandbox/e2b_runner.start_sandbox`, `run_pytest`) — exponential backoff, `max_attempts=3`, no infinite loops (rule §3.6).
- `Procfile` + `railway.toml` at repo root — single worker process running `python main.py`.
- `.github/workflows/notify.yml` — CI run-status webhook that POSTs to a Telegram bot endpoint.
- `tests/test_checkpoint_saver.py` — minimal interface tests against the JSON checkpoint saver (mock the underlying `agent.checkpoints` module).
- `tests/test_main_wiring.py` — smoke test that `main.compose_deps()` returns an `OrchestratorDeps` with all required callbacks set when real env vars are present.

**Out of scope**
- Studio production deployment. Studio remains a dev tool only.
- Multi-tenant secret isolation. Single operator per deployment.

**Hard guards**
- Tenacity wraps must have a hard ceiling on total wait time (e.g. `stop_after_delay(60)`) so we never block the loop indefinitely.
- `compose_deps` raises `SettingsError` if any non-optional setting is missing, before the bot opens long-polling.
- Telegram approval keyboard `callback_data` carries an HMAC over `task_id + action` to prevent spoofing if the bot ends up in a group.
- Railway deploy never gets read access to a personal GitHub token. Use a deploy-scoped fine-grained token only.

**Milestone**
- Deploy succeeds on Railway, `/start` works against the live bot.
- End-to-end task from phone completes — clone → plan → write → tests → approval keyboard → PR opened → lesson saved → next task pulls it.
- A failed GitHub Actions run on the agent's PR triggers a Telegram message with the run URL.

**Tests**
- `uv run pytest tests/ -v --cov=. --cov-fail-under=70`
- Checkpoint saver: put / get_tuple / list round-trip.
- Wiring: every `OrchestratorDeps` field populated.
- Tenacity: retried after one transient error, fails fast on permanent error.

**Definition of done**
- All prior tests still pass.
- New tests pass.
- `uv run ruff check .` and `uv run black --check .` clean.
- Coverage ≥ 70% overall (Phase 6 gate).
- Successful deploy on Railway, live bot completes one PR end-to-end.
- This file updated to mark Phase 6 done and the project ready for ongoing iteration.
- `.claude/CLAUDE.md` §11 snapshot updated.

---

## Setup reminder (every fresh checkout)

```bash
uv venv --python 3.11   # only if .venv/ is missing
uv sync --all-groups
cp .env.example .env    # then fill in real values
uv run python main.py
```

### LangGraph Studio + LangSmith

```bash
# 1. Get a key at https://smith.langchain.com → API Keys
# 2. Set in .env:
#    LANGCHAIN_TRACING_V2=true
#    LANGCHAIN_API_KEY=ls_...
#    LANGCHAIN_PROJECT=clawcode

# Launch Studio (opens browser, watches agent/orchestrator.py:graph)
uv run langgraph dev
```

Studio reads `langgraph.json` at repo root. Every node + tool call streams to LangSmith under the project name. Disable tracing by unsetting or flipping `LANGCHAIN_TRACING_V2=false`.

---

## Phase ledger

| Phase | Status | Notes |
|---|---|---|
| 0 — Environment Setup | ✅ done | Settings, .env.example, uv, CI, test_settings green |
| 1 — Telegram Skeleton | ✅ done | handler/commands/keyboards + 24 bot tests green |
| 2 — GitHub Tools | ✅ done | gh/{repo_manager,pr_manager,exceptions}; 19 new tests; 93% coverage |
| 3 — E2B Sandbox | ✅ done | sandbox/{e2b_runner,exceptions}; RunResult, timeout, scrub, truncate, idempotent shutdown; 18 new tests; 95% coverage |
| 4 — Agent Brain | ✅ done | LangGraph `StateGraph` (chat→tools→post_tools→{chat\|finalize\|abort}); LangChain `@tool`s, ChatGroq, LangSmith tracing, Studio entry at `langgraph.json`; 90 tests; 96% coverage |
| 5 — Memory + Voice | ✅ done | memory/{store,exceptions}; agent/memory; bot/voice + /resume; lesson recall+save plumbed into orchestrator; 32 new tests; 95% coverage |
| 6 — Polish + Deploy | ✅ done | agent/wiring compose_deps; bot/approval gate + HMAC keyboards + CallbackQueryHandler; tenacity wraps on open_pr/push_branch/start_sandbox/run_pytest + ChatGroq.with_retry; main.py wires dispatch/resume/transcribe/approval into bot_data; Procfile + railway.toml + .github/workflows/notify.yml; 138 tests; 93% coverage |

Full phase details: [build-plan.md](build-plan.md) and CLAUDE.md §5.

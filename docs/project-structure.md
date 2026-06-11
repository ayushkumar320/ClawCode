# Project Structure

## Directory Layout

```
ClawCode/
├── main.py                  # Entry point — wires bot + settings, no business logic
├── requirements.txt         # Pinned dependencies
├── .env                     # Secrets (never committed)
├── .env.example             # Template for required env vars
├── Procfile                 # Railway deployment
├── railway.toml             # Railway config
│
├── config/
│   ├── __init__.py
│   └── settings.py          # Loads + validates .env, raises on missing keys
│
├── bot/
│   ├── __init__.py
│   ├── handler.py           # PTB Application setup, routes updates to commands
│   ├── commands.py          # Command callbacks (/start, /repo, /status, /cancel, /resume)
│   └── keyboards.py         # Inline keyboards (approve/reject) — stateless
│
├── agent/
│   ├── __init__.py
│   ├── orchestrator.py      # Agentic loop — Groq calls, tool dispatch, checkpointing
│   ├── tools.py             # Tool schemas + dispatch to repo_manager/e2b_runner
│   └── memory.py            # Lesson save/retrieve via memory/store.py
│
├── gh/
│   ├── __init__.py
│   ├── repo_manager.py      # Clone, read, write, branch, commit, push
│   └── pr_manager.py        # Open/update PRs, post comments
│
├── sandbox/
│   ├── __init__.py
│   └── e2b_runner.py        # E2B sandbox lifecycle — upload repo, run pytest, shutdown
│
├── memory/
│   ├── __init__.py
│   └── store.py             # ChromaDB collection wrapper — knows nothing about agents
│
├── checkpoints/             # JSON snapshots of agent state (never committed)
│   └── .gitkeep
│
├── tests/
│   ├── __init__.py
│   ├── test_settings.py
│   ├── test_bot.py
│   ├── test_repo_manager.py
│   ├── test_pr_manager.py
│   ├── test_e2b_runner.py
│   ├── test_orchestrator.py
│   └── test_memory.py
│
└── docs/
    ├── project-structure.md    # This file
    └── improvements.md         # Planned improvements and gaps
```

## Module Boundaries

| Module | Talks To | Never Touches |
|---|---|---|
| `bot/` | `agent/orchestrator` | GitHub, E2B, ChromaDB |
| `agent/orchestrator` | `agent/tools`, `agent/memory` | Telegram, GitHub APIs directly |
| `agent/tools` | `gh/repo_manager`, `sandbox/e2b_runner` | LLM, Telegram |
| `gh/repo_manager` | Git, filesystem | PRs, Telegram |
| `gh/pr_manager` | GitHub API | File modifications |
| `sandbox/e2b_runner` | E2B API | Persistence, Telegram |
| `memory/store` | ChromaDB | Agents, Telegram |

## Data Flow

```
User (Telegram)
  → bot/handler.py (auth + routing)
    → bot/commands.py (parse command)
      → agent/orchestrator.py (agentic loop)
        → agent/tools.py (dispatch)
          → gh/repo_manager.py (read/write files)
          → sandbox/e2b_runner.py (run tests)
          → memory/store.py (retrieve lessons)
        → checkpoints/ (save state after each tool call)
      ← agent returns diff summary
    ← bot asks user to approve/reject
  → on approval: gh/pr_manager.py opens PR
  ← PR URL sent back to user
```

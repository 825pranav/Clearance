# Progress

Build log for Clearance, following `SPEC.md` phase by phase. Each phase lists its gate command, a summary of the output, and the result.

## Preflight

| Check | Result |
|---|---|
| `.env` | Created from `.env.example` with local defaults (Postgres on localhost, `GITLAB_DRY_RUN=1`, Ollama at `http://localhost:11434/v1`, key `ollama`) |
| Docker | Docker Desktop was not running; started it. Engine 29.7.2, Compose v5.5.1 |
| Ollama | Was not running; started `ollama serve`. 0.35.1 |
| GPU | RTX 4050 Laptop, 6 GB VRAM |
| Tool-capable Ollama models | `qwen3:4b` (2.5 GB), `llama3.2` (3B, 2.0 GB), `qwen2.5:7b` (4.7 GB), `qwen3:8b` (5.2 GB), `gemma4:12b` (7.6 GB, too big for 6 GB) and `pd-qwen2.5-7b-12k` (a 12K-context copy of qwen2.5:7b). Candidates written to `evals/models.yaml` |
| `LLM_MODEL` | Unset; chosen in phase 5b |
| `make` | Not installed; installed GNU Make 4.4.1 with `winget install ezwinports.make` |
| GitLab token / project | Missing: building against the dry-run client |
| Slack tokens | Missing: bot, tests and manifest are written; the app is created later from the manifest |
| `DEMO_EMPLOYEE_EMAIL` | Unset |

Env vars set at the start: `DATABASE_URL`, `LLM_BASE_URL`, `LLM_API_KEY`, `GITLAB_URL`, `GITLAB_DRY_RUN`. Unset: `LLM_MODEL`, `GITLAB_TOKEN`, `GITLAB_PROJECT_ID`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `DEMO_EMPLOYEE_EMAIL`.

## Phase 0: Setup

- Gate: `make up` → container healthy; `python -m app.db ping` → `ok`; `pytest -q` → `2 passed`.
- Result: **pass**

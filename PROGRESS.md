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

## Phase 1: Data and frozen evals

- Built: `app/schema.sql` (5 tables), `data/seed.sql` (12 employees, 10 systems, 7 baselines), 12 handbook docs, `evals/cases.yaml` (30), `evals/adversarial.yaml` (12), `evals/retrieval_cases.yaml` (15), `evals/models.yaml`.
- Gate: `make seed` → `seeded`; `pytest tests/test_seed_integrity.py` → `8 passed`.
- Result: **pass**. The eval files are frozen from this point.

## Phase 2: Policy core

- Built: `app/policy.py` (`level_rank`, `covers`, `effective_risk`, `required_approvers`, `validate_justification`, `existing_access`) and the catalogue/request/audit queries in `app/db.py`.
- Gate: `pytest tests/test_policy.py` → `31 passed` (each risk tier, admin override, self-approval, the 7/8-word boundary, level ordering, all four `existing_access` results, plus a check that every filed eval expectation follows from the rules).
- Result: **pass**

## Phase 3: Retrieval

- Built: `app/retrieval.py`: chunk by `##` heading (61 chunks), embed with fastembed `BAAI/bge-small-en-v1.5` (local ONNX, ~67 MB download on first run), `VectorStore` (`add`, `search`, `save`, `load`) on a normalised NumPy matrix, persisted to `data/index/` by `make index`.
- Gate: retrieval eval **15/15** expected files in the top 3 (gate: 13/15). `tests/test_retrieval.py` → `5 passed`.
- Result: **pass**

## Phase 4: GitLab client, tools, MCP server

- Built: `app/gitlab_client.py` (`DryRunGitLab` and `GitLabClient`, same five methods), `app/tools.py` (four tools, structured errors, a `tool_called` audit row per call), `templates/access_request.md`, `app/mcp_server.py` (MCP 2.x `MCPServer` over stdio).
- Gate: `pytest tests/test_tools.py` → `12 passed`: valid request (row, audit rows, issue with every section and the three labels), baseline refused, pending duplicate refused, short high-risk justification → `justification_required`, high risk → two distinct approvers, MCP stdio server lists exactly four tools and `search_handbook` returns results.
- Real GitLab smoke test: **skipped**, no `GITLAB_TOKEN`/`GITLAB_PROJECT_ID`. Steps are in `HANDOFF.md`.
- Result: **pass**

## Direction check A

1. **The system in six sentences.** An employee writes to a Slack bot in plain English. The bot looks up who they are and passes the message to an agent loop that gives an LLM four tools served over MCP. The LLM works out which system and access level is meant, checks existing access, searches the handbook, and asks a follow-up question when something is missing. When it calls `create_access_request`, Python code recomputes everything that matters (existing access, risk tier, approvers, justification rule) and files a GitLab issue from a template. A sync job polls the issue's labels and moves the request through its statuses, notifying the requester. A Streamlit page shows requests, the audit trail and eval scores.
2. **Is any policy decision reachable by the LLM other than through `create_access_request` inputs?** No. The tools take only `system_key`, `access_level`, `justification` and `query`; risk, approvers, status and the duplicate check are computed in `policy.py` and `tools.py`. `employee_email` and `conversation_id` are session parameters that the agent strips from the schemas and fills in itself (implemented in phase 5).
3. **Code the spec did not ask for?** Two small helpers: `resolve_system` accepts a display name or alias as well as the key (removes a whole class of "unknown system" round trips with small models), and `check_existing_access` also reports the risk tier and whether a justification will be needed, so the model knows whether to ask for one. Both are part of existing tools, not new features. Nothing removed.
4. **Lines of Python outside `tests/` and `evals/`:** 653.
5. **`make test`:** `58 passed`. All earlier gates are still green.

## Phase 5: Agent loop and CLI

- Built: `app/llm.py` (OpenAI-compatible client, temperature 0, exponential backoff on 429s), `app/agent.py` (`ToolClient` keeps one MCP stdio session open on a background event loop; `Agent.handle_message` runs up to 6 tool rounds; session parameters are stripped from the schemas and injected; outcome derived from tool results), `app/cli.py`, `evals/run_evals.py`.
- Gate: `make eval-smoke` with `LLM_MODEL=clearance-qwen2.5-7b` → **5/5, 0 safety violations**, 4.0 s per reply. `make chat` (scripted three turns as Alex Chen): asked for the level, filed Tableau read on the second turn with the real dry-run link and the right approver.
- Scripted fake-LLM tests of the loop: `tests/test_agent.py` → `10 passed` (no network).
- Result: **pass**
- What it took (failures found and fixed, in the spec's preferred order):
  1. *Tool result messages*: the small model asked for a justification the user had already given. `check_existing_access` now says what to do next, and `search_handbook` results remind the model to name the source file.
  2. *Tool descriptions and prompt*: qwen2.5-7b reliably makes one tool call per turn but often stops after `check_existing_access` instead of making the second call. Since `create_access_request` already re-runs the existing-access check in code before it looks at the justification, the model is now told to call it as soon as it knows the system and level. Nobody gets asked for a reason they don't need, because code checks access first. `check_existing_access` remains for "do I already have X?" questions. Recorded in `DECISIONS.md`.
  3. *Code*: the model twice told the user a request was filed, with an invented GitLab link, when nothing had been filed. `Agent` now checks every reply against the tool results from the same turn: a filing claim needs a successful `create_access_request`, and every link or `.md` file named must appear in a tool result. On the first miss the model gets one correction round; on a second miss a fixed safe reply is sent instead.
- Known weakness seen in `make chat`: on a policy question asked mid-conversation after a filing, the model answered without searching and named a non-existent approver ("Rajiv Patel"). The guard catches invented links and file names but not invented people.

## Phase 5b: Pick the model

- Gate: `make eval-smoke MODEL=<name>` for each local candidate (`qwen2.5-7b`, `llama3.2-3b`, `qwen3-4b`, `qwen3-8b`); hosted candidates have no keys and are marked as estimates.
- Result: **pass**. `DECISIONS.md` has the table; chosen `clearance-qwen2.5-7b` at 5/5, 0 safety violations, 3.96 s per reply.

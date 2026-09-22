# Decisions

One line per ambiguity or deviation from `SPEC.md`, with the reason.

## Setup

- The project is named **Clearance**, so the database is `clearance` instead of `access_agent` and the repo folder is `clearance/`.
- `mcp` installed as 2.3.0. `FastMCP` is now `mcp.server.mcpserver.MCPServer` and result fields are snake_case (`input_schema`, `is_error`); the code uses the 2.x API.
- Tests use a separate `<db>_test` database and evals use `<db>_eval`, so running either never wipes the demo data in the main database.
- On Windows the Makefile runs recipes under `cmd.exe` so the venv path `.venv\Scripts\python.exe` works; on Linux (CI) it uses `.venv/bin/python`. Override with `make test PY=python`.

## Data

- Seed has 12 employees, not 10, so that every system owner is a different person from the requesters' managers. Morgan Lee is the top of the tree and has no manager (`manager_email` is NULL). Riley Kim's role, "Operations Manager", is not in the spec's role list; Sales Ops, Support and Design needed a manager who was not an engineering manager.
- IT (Kai Walker) owns the business SaaS tools (Salesforce, Zendesk, Figma) and Okta, Infrastructure (Devon Price) owns the AWS/GCP accounts and Data Platform (Lena Fischer) owns Snowflake and Tableau.
- Eval files add a few fields to the spec's format: `expect.turn_outcomes` for multi-turn cases, `expect.cites` for policy questions (a list, because some questions are correctly answered from more than one file), and `allowed_requests`/`marker` in the adversarial suite so "fooled" is decided by code, not by reading replies.
- `policy-01` accepts either `aws-production.md` or `access-request-process.md`, because both files genuinely describe the production approval process.

## Policy

- Approvers are stored as `[{"role": "manager"|"owner", "email": ...}]`. When the requester owns the system, the owner slot is filled by their manager, so the role labels stay the same and the sync job still looks for both approval labels.
- A requester with no manager on file (only Morgan Lee, the top of the tree) cannot be routed; `create_access_request` returns `no_manager` instead of guessing an approver.
- Rejected requests are ignored by `existing_access`, so someone can ask again after a rejection.

## Agent

- The model is told to call `create_access_request` as soon as it knows the system and level, instead of always calling `check_existing_access` first. The spec's goal ("check existing access before filing, so people are not asked for details they will not need") holds because `create_access_request` runs the existing-access check in code *before* the justification check. Reason: qwen2.5-7b rarely makes two tool calls in a row, and this keeps the decision in code rather than in the model's chaining.
- Conversation history keeps only the user's messages and the final replies, not tool calls and results. That is enough for multi-turn requests, and it keeps an 8K context from filling up.
- After the last allowed tool round, the model is called once more without tools, so a conversation always ends with a text reply.
- Added a reply check in `Agent` (not in the spec): a reply that claims a filing, shows a link, or names a handbook file must be backed by a tool result from the same turn. Otherwise the model gets one correction round, then a fixed safe reply. Reason: the chosen local model invented filings and links during phase 5, and telling an employee they have filed a request when they have not is a real failure even if no database invariant breaks.
- `evals/run_evals.py` counts a `duplicate`-category case as passing on either `duplicate` or `already_has`, as section 13's table allows.

## Phase 5b: model choice

All runs: the 5 smoke cases, same prompt and tools, Ollama on an RTX 4050 Laptop (6 GB), each model with an 8K context (`clearance-*` Ollama models, see `evals/models.yaml`). Numbers are from `evals/results.json` → `smoke`.

| Candidate | Smoke passed | Safety violations | Malformed tool calls | Avg s per reply | Verdict |
|---|---|---|---|---|---|
| qwen2.5-7b (`clearance-qwen2.5-7b`) | 5/5 | 0 | 0 | 3.96 | **chosen** |
| qwen3-4b (`clearance-qwen3-4b`) | 5/5 | 0 | 0 | 19.14 | tie on passes, slower; earlier runs of the same model measured 20.3 s and 37.1 s, so it sits at or over the 20 s limit |
| qwen3-8b (`clearance-qwen3-8b`) | 5/5 | 0 | 0 | 30.34 | dropped: over 20 s per reply |
| llama3.2-3b (`clearance-llama3.2`) | 3/5 | 0 | 0 | 1.35 | fewer passes; invented issue links before the reply check existed |
| groq-llama-3.3-70b | not run | | | | **estimate, not measured:** no `GROQ_API_KEY`. A 70B model would very likely pass 5/5 at 1–2 s per reply, but the free tier's rate limits would slow a 30-case run |
| gemini-2.5-flash | not run | | | | **estimate, not measured:** no `GEMINI_API_KEY`. Likely 5/5 with good tool calling, again limited by free-tier rate limits |

- **Choice: `clearance-qwen2.5-7b`.** It ties for the most smoke passes and is the fastest of the tied models by a factor of five, which matters for a Slack demo. It is set as `LLM_MODEL` in `.env`.
- The qwen3 models think before every reply. Ollama's OpenAI-compatible endpoint ignored `think: false`, and both `reasoning_effort: "none"` and the `/no_think` tag left the reasoning in place (it moved into the reply text), so there was no clean way to turn it off without leaving the OpenAI-compatible API.
- qwen2.5-7b with an 8K context uses about 5.4 GB and runs partly on the CPU (Ollama reports 24% CPU / 76% GPU); it is still around 4 s per reply.

## Phase 6

- `create_access_request.justification` is a required parameter (an empty string means "no reason given"). With it optional, qwen2.5-7b left it out even when the user's message contained a reason.
- The agent checks required tool arguments before calling the MCP server and returns a structured `invalid_arguments` error naming what is missing. The MCP SDK's own validation error was too generic for a small model to act on.
- Phase 6 ran after the D1/D2 code was written (but before those gates were committed), so the eval numbers describe the final lifecycle code.

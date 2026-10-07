# Clearance

Clearance is a Slack agent for employee access requests. Someone writes "I need read access to Snowflake to build the churn report for finance", and Clearance works out the system and access level, checks whether they already have it, applies the access policy, and files a GitLab issue from a standard template, routed to the right approvers. It never grants access itself. A sync job watches the issue's approval labels, moves the request through its lifecycle and messages the requester.

**Design doc:** [`docs/DESIGN.md`](docs/DESIGN.md) has the architecture diagrams, the threat model, and an explanation of every failed eval case.

## The design rule

**The LLM understands language. Plain Python code makes every policy decision.**

The model decides which system and level the person means, asks a follow-up question when something is missing, and writes the reply. Code decides the risk tier, the approvers, whether a justification is good enough, whether the request is a duplicate, who the requester is, and what state the request is in.

This is enforced by the tool interfaces, not by the prompt:

- `create_access_request` takes only `system_key`, `access_level` and `justification`. There is no parameter for risk, approvers or status, so the model cannot set them.
- `employee_email` is a *session parameter*. The agent removes it from the tool schemas the model sees and fills it in from the Slack identity on every call, so "file this for my manager" cannot work.
- `create_access_request` re-runs the existing-access check itself, so skipping the check tool does not matter.
- The outcome reported for a message (`filed`, `already_has`, `duplicate`, `no_action`) is derived from tool results, never from the model's wording.
- Replies are checked against the tool results of the same turn. A reply that says a request was filed, that the user already has access, shows a link, or names a handbook file must be backed by a tool result. Otherwise the model gets one correction round, then a fixed safe reply is sent.

## Architecture

```
 Slack DM / @mention                                  terminal: make chat
        |                                                     |
        v                                                     v
 app/slack_bot.py  -- Slack user -> employee email --> app/agent.py  handle_message()
   (Bolt, Socket Mode)                                   |  tool-calling loop, max 6 rounds, temperature 0
        |                                                |  strips/injects employee_email + conversation_id
        |                                                |  checks replies against tool results
        |                                     app/llm.py |  OpenAI-compatible client (Ollama, Groq, Gemini...)
        |                                                |
        |                                     MCP over stdio (one long-lived subprocess)
        |                                                v
        |                                     app/mcp_server.py -> app/tools.py
        |                                        search_handbook        -> app/retrieval.py (fastembed + NumPy)
        |                                        get_employee           -> app/db.py (Postgres, hand-written SQL)
        |                                        check_existing_access  -> app/policy.py (pure functions)
        |                                        create_access_request  -> policy + db + app/gitlab_client.py
        |
        +-- background thread: app/sync.py, every 30 s
              reconcile() stuck filings; approval labels, only if added by that approver -> policy.transition() -> db.advance()
              swap status:: label, DM the requester

 dashboard/app.py (Streamlit): counts, request table, audit trail, eval scores
```

**Request lifecycle** (`policy.transition`, the only way a status changes):

```
filing --issue_created--> pending --manager_approved--> approved             (low, medium)
   |                         |  \--first approval--> partially_approved --second approval--> approved   (high)
   +--issue_failed--> failed +--rejected--> rejected  (from pending or partially_approved)
```

**Crash-safe filing.** The request row is inserted as `filing` with a fresh UUID, the GitLab issue is created with that UUID hidden in an HTML comment, and then the two are linked. If the process dies in between, `reconcile()` finds the issue by its UUID or marks the row `failed`. A partial unique index allows only one open request per employee per system, so concurrent duplicates cannot both get in.

## Setup

Requirements: Python 3.11+, Docker, GNU make, and an OpenAI-compatible LLM endpoint with tool calling. The default is a local Ollama model.

```bash
python -m venv .venv                      # or: uv venv .venv
.venv/bin/pip install -r requirements.txt # Windows: .venv\Scripts\pip install -r requirements.txt
cp .env.example .env                      # then fill in the LLM_* values

make up        # Postgres in Docker
make seed      # schema + mock employees, systems and baselines
make index     # embed the handbook (downloads a ~67 MB model on first run)
make test      # unit, property, crash, race, MCP, Slack and dashboard tests; no network, no LLM
make chat      # talk to the agent in the terminal (dry-run GitLab by default)
```

Local model used for the results below (Ollama, 6 GB GPU), with an 8K context window:

```bash
ollama pull qwen2.5:7b
printf 'FROM qwen2.5:7b\nPARAMETER num_ctx 8192\n' > Modelfile && ollama create clearance-qwen2.5-7b -f Modelfile
# .env: LLM_BASE_URL=http://localhost:11434/v1  LLM_API_KEY=ollama  LLM_MODEL=clearance-qwen2.5-7b
```

Other targets: `make eval`, `make eval-smoke`, `make eval-adversarial`, `make slack`, `make sync`, `make dashboard`. Real GitLab and Slack need tokens; see `HANDOFF.md`, "Finish setup".

## Eval results

All numbers come from `evals/results.json` (rendered in `evals/results.md`). The eval cases were written before any agent code and frozen; the one later change to a case is recorded in `DECISIONS.md`. Evals check outcomes and database rows, not the wording of replies. Model: `clearance-qwen2.5-7b` (qwen2.5 7B, Q4, 8K context) on an RTX 4050 Laptop GPU.

**Main suite: 27/30 passed, 0 safety violations.** 3.93 s per reply on average, 2.3 LLM calls per case.

| Category | Passed |
|---|---|
| clear request | 9/10 |
| vague, then details | 4/4 |
| covered by role baseline | 3/3 |
| duplicate of open/approved request | 3/3 |
| high risk | 3/4 |
| policy question | 3/3 |
| adversarial | 2/3 |

Safety invariants checked on every case: risk tier matches `effective_risk`, approvers match `required_approvers`, the request is for the session's employee, and new requests start `pending`. 0 violations.

**Adversarial suite: harm 0/12, fooled 2/12.** *Harm* means a safety invariant broke. *Fooled* means the model went along with the attack: it filed something the user did not legitimately ask for, repeated injected text, or claimed access had been granted.

| Category | Fooled | Harm |
|---|---|---|
| direct override | 0/3 | 0/3 |
| false authority | 0/3 | 0/3 |
| impersonation | 1/3 | 0/3 |
| poisoned document | 1/3 | 0/3 |

**Retrieval: 15/15** questions have the expected handbook file in the top 3.

**Consistency:** the main suite run three times gave the same outcome for **30/30** cases.

**Model choice** (smoke cases, `DECISIONS.md` has the full table): qwen2.5-7b and both qwen3 models passed 5/5. qwen2.5-7b won on speed (3.96 s per reply against 19.14 s and 30.34 s). llama3.2-3b passed 3/5.

## Known limitations

- **Approvals are labels, so they must come from the right person.** The first version counted an `approved::owner` label whoever added it. That gap is now closed: the sync job reads GitLab's label history and only counts a label added by that slot's approver (see threat T9 in `docs/DESIGN.md`). Approvers' GitLab usernames are kept by hand in `employees.gitlab_username`; a real deployment would sync them from the identity provider.
- The local 7B model is the weak link. It misses 3 of 30 cases (it doesn't retry after a missing-argument error, claims a filing it didn't make, and over-refuses a mixed legitimate/illegitimate message). In one adversarial case it filed a request after an impersonation story (under the real user's identity, so no harm), and in another it repeated a poisoned handbook instruction to the user. Code keeps every invariant intact, but the wording of replies is only as good as the model.
- The "fooled" detector and the reply check are pattern-based. They catch the false claims seen during the build, not every possible phrasing.
- In dry-run mode the GitLab issues live in the memory of the MCP tool-server process, so the separate sync process cannot see them. The approval flow is tested in-process, and live approval needs real GitLab.
- Conversation history lives in memory, so restarting the bot forgets open conversations. Requests and the audit log are in Postgres and survive.
- No authentication on the dashboard; it is meant to run locally.

## About the handbook and data

The twelve handbook pages in `data/handbook/` are **mock policies written for this project**, organised the way a public company handbook organises access-request pages (one page per system plus a process page and a least-privilege page). No text is copied from any real handbook. All employees, emails and systems in `data/seed.sql` are fictional.

## Layout

```
app/          config, db, policy, retrieval, gitlab_client, tools, mcp_server, llm, agent, cli, slack_bot, sync
dashboard/    Streamlit page
data/         handbook pages and seed.sql
evals/        cases.yaml, adversarial.yaml, retrieval_cases.yaml, models.yaml, run_evals.py, results.json/.md
templates/    GitLab issue template
tests/        pytest suite: policy, state machine (hypothesis), tools, MCP, crash/race, sync, Slack, dashboard
```

`SPEC.md` is the original build spec. `PROGRESS.md` logs each phase and its gate, `DECISIONS.md` lists every deviation and judgement call, and `HANDOFF.md` covers what is left to configure.

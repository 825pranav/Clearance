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

# Decisions

One line per ambiguity or deviation from `SPEC.md`, with the reason.

## Setup

- The project is named **Clearance**, so the database is `clearance` instead of `access_agent` and the repo folder is `clearance/`.
- `mcp` installed as 2.3.0. `FastMCP` is now `mcp.server.mcpserver.MCPServer` and result fields are snake_case (`input_schema`, `is_error`); the code uses the 2.x API.
- Tests use a separate `<db>_test` database and evals use `<db>_eval`, so running either never wipes the demo data in the main database.
- On Windows the Makefile runs recipes under `cmd.exe` so the venv path `.venv\Scripts\python.exe` works; on Linux (CI) it uses `.venv/bin/python`. Override with `make test PY=python`.

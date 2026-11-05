"""Postgres connection helper and every SQL query the app runs.

One short-lived connection per call keeps this simple; nothing here is hot enough to need a pool.
"""

import sys

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import config, policy

SCHEMA = config.ROOT / "app" / "schema.sql"
SEED = config.ROOT / "data" / "seed.sql"
CONSOLE_GRANTS = config.ROOT / "app" / "console_grants.sql"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or config.DATABASE_URL, row_factory=dict_row, autocommit=True)


def ping() -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


def ensure_database(url: str) -> None:
    """Create the database named in `url` if it does not exist (used for the test and eval databases)."""
    info = psycopg.conninfo.conninfo_to_dict(url)
    name = info["dbname"]
    admin_url = psycopg.conninfo.make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')


def reset() -> None:
    """Drop and recreate every table, then load the seed data."""
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(SEED.read_text(encoding="utf-8"))
        conn.execute(CONSOLE_GRANTS.read_text(encoding="utf-8"))


def setup_console_role(password: str) -> None:
    """Give the console its own login, limited by console_grants.sql. Run after `manage.py migrate`."""
    with connect() as conn:
        if conn.execute("SELECT to_regclass('public.requests') AS found").fetchone()["found"] is None:
            sys.exit("The app's tables do not exist yet. Run `make seed` first.")
        conn.execute(CONSOLE_GRANTS.read_text(encoding="utf-8"))
        conn.execute(sql.SQL("ALTER ROLE clearance_console LOGIN PASSWORD {}").format(sql.Literal(password)))


# ---------------------------------------------------------------- directory and catalogue


def get_employee(email: str) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM employees WHERE email = %s", (email,)).fetchone()


def get_employee_by_slack_id(slack_user_id: str) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM employees WHERE slack_user_id = %s", (slack_user_id,)).fetchone()


def list_systems() -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM systems ORDER BY key").fetchall()


def resolve_system(name: str) -> dict | None:
    """Find a system by key, display name or alias, ignoring case."""
    name = name.strip().lower()
    with connect() as conn:
        return conn.execute(
            """SELECT * FROM systems
               WHERE lower(key) = %s OR lower(name) = %s OR %s = ANY(SELECT lower(a) FROM unnest(aliases) a)""",
            (name, name, name),
        ).fetchone()


def baseline_level(role: str, system_key: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT access_level FROM role_baseline WHERE role = %s AND system_key = %s", (role, system_key)
        ).fetchone()
    return row["access_level"] if row else None


# ---------------------------------------------------------------- requests and audit


def requests_for(employee_email: str, system_key: str) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM requests WHERE employee_email = %s AND system_key = %s ORDER BY id",
            (employee_email, system_key),
        ).fetchall()


def insert_request(employee_email: str, system_key: str, access_level: str, justification: str,
                   risk_tier: str, approvers: list[dict], status: str = "filing", idempotency_key=None) -> int:
    """Raises psycopg.errors.UniqueViolation if the employee already has an open request for this system."""
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO requests (employee_email, system_key, access_level, justification, risk_tier, approvers,
                                     status, idempotency_key)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (employee_email, system_key, access_level, justification, risk_tier, Jsonb(approvers), status,
             idempotency_key),
        ).fetchone()
    return row["id"]


def attach_issue(request_id: int, iid: int, url: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE requests SET gitlab_issue_iid = %s, gitlab_issue_url = %s, updated_at = now() WHERE id = %s",
            (iid, url, request_id),
        )


def advance(request_id: int, event: str, actor: str) -> policy.State:
    """Apply one lifecycle event. The only code that writes a request's status.

    The row is locked while the transition is computed, so the sync job and reconcile cannot overwrite each
    other. A change (status or recorded approvals) writes a `status_changed` audit row.
    """
    with connect() as conn, conn.transaction():
        row = conn.execute("SELECT * FROM requests WHERE id = %s FOR UPDATE", (request_id,)).fetchone()
        old = policy.State(row["status"], frozenset(row["approvals"]))
        new = policy.transition(old, event, row["risk_tier"])
        if new != old:
            conn.execute("UPDATE requests SET status = %s, approvals = %s, updated_at = now() WHERE id = %s",
                         (new.status, sorted(new.approvals), request_id))
            detail = {"event": event, "from": old.status, "to": new.status, "approvals": sorted(new.approvals)}
            conn.execute("INSERT INTO audit_log (request_id, actor, event, detail) VALUES (%s, %s, 'status_changed', %s)",
                         (request_id, actor, Jsonb(detail)))
    return new


def requests_with_status(statuses: tuple[str, ...]) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM requests WHERE status = ANY(%s) ORDER BY id", (list(statuses),)).fetchall()


def requests_stuck_filing(older_than_seconds: int) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM requests WHERE status = 'filing' AND created_at < now() - make_interval(secs => %s) ORDER BY id",
            (older_than_seconds,),
        ).fetchall()


def audit(event: str, actor: str, detail: dict | None = None, conversation_id: str | None = None,
          request_id: int | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (conversation_id, request_id, actor, event, detail) VALUES (%s, %s, %s, %s, %s)",
            (conversation_id, request_id, actor, event, Jsonb(detail or {})),
        )


def approver_gitlab_usernames(approvers: list[dict]) -> dict[str, str | None]:
    """Approver slot -> that approver's GitLab username (None if not mapped, so their labels never count)."""
    with connect() as conn:
        return {a["role"]: (conn.execute("SELECT gitlab_username FROM employees WHERE email = %s", (a["email"],))
                            .fetchone() or {}).get("gitlab_username") for a in approvers}


def audit_once(event: str, actor: str, detail: dict, request_id: int) -> None:
    """Like audit(), but skips an identical row that already exists (the sync job sees the same labels every poll)."""
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM audit_log WHERE request_id = %s AND event = %s AND detail = %s",
                              (request_id, event, Jsonb(detail))).fetchone()
    if not exists:
        audit(event, actor, detail, request_id=request_id)


# ---------------------------------------------------------------- dashboard


def list_requests() -> list[dict]:
    with connect() as conn:
        return conn.execute(
            """SELECT r.*, e.name AS employee_name FROM requests r
               JOIN employees e ON e.email = r.employee_email ORDER BY r.id DESC"""
        ).fetchall()


def audit_for(request_id: int) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT created_at, actor, event, detail FROM audit_log WHERE request_id = %s ORDER BY id", (request_id,)
        ).fetchall()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "ping"
    if command == "ping":
        print("ok" if ping() else "failed")
    elif command == "map-approvers":
        # Demo helper: let one GitLab account act for every manager and system owner.
        with connect() as conn:
            updated = conn.execute(
                """UPDATE employees SET gitlab_username = %s WHERE email IN
                   (SELECT manager_email FROM employees UNION SELECT owner_email FROM systems)""", (sys.argv[2],)).rowcount
        print(f"{updated} approvers now map to GitLab user {sys.argv[2]}")
    elif command == "console-role":
        if not config.CONSOLE_DB_PASSWORD:
            sys.exit("Set CONSOLE_DB_PASSWORD first.")
        setup_console_role(config.CONSOLE_DB_PASSWORD)
        print("console role ready")
    elif command == "seed":
        ensure_database(config.DATABASE_URL)
        reset()
        print("seeded")
    else:
        sys.exit(f"unknown command: {command}")

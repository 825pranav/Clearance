"""Postgres connection helper and every SQL query the app runs.

One short-lived connection per call keeps this simple; nothing here is hot enough to need a pool.
"""

import sys

import psycopg
from psycopg.rows import dict_row

from app import config

SCHEMA = config.ROOT / "app" / "schema.sql"
SEED = config.ROOT / "data" / "seed.sql"


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


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "ping"
    if command == "ping":
        print("ok" if ping() else "failed")
    elif command == "seed":
        ensure_database(config.DATABASE_URL)
        reset()
        print("seeded")
    else:
        sys.exit(f"unknown command: {command}")

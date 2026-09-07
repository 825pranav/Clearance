"""Shared test setup.

Tests run against their own database (the configured one with a `_test` suffix) and always use the
dry-run GitLab client, so `make test` never touches demo data or the network.
"""

import os

import psycopg
from dotenv import dotenv_values

_base = os.environ.get("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL") or \
    "postgresql://postgres:postgres@localhost:5432/clearance"
_name = psycopg.conninfo.conninfo_to_dict(_base)["dbname"]
if not _name.endswith("_test"):
    _base = psycopg.conninfo.make_conninfo(_base, dbname=f"{_name}_test")
os.environ["DATABASE_URL"] = _base
os.environ["GITLAB_DRY_RUN"] = "1"

import pytest  # noqa: E402

from app import db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    db.ensure_database(os.environ["DATABASE_URL"])


@pytest.fixture
def seeded():
    """A freshly reset database with the seed data loaded."""
    db.reset()
    yield

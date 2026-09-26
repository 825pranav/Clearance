"""Crash-safe filing (phase D2): both crash points, reconcile, and a race of 8 identical requests."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import db, gitlab_client, sync, tools

ALEX = "alex.chen@example.com"
REASON = "to build the weekly churn report for the finance team every Monday"


@pytest.fixture
def gl(seeded):
    client = gitlab_client.DryRunGitLab()
    gitlab_client.set_client(client)
    yield client
    gitlab_client.set_client(None)


def _rows():
    with db.connect() as conn:
        return conn.execute("SELECT * FROM requests ORDER BY id").fetchall()


def _age_filing_rows():
    """Pretend the crash happened a while ago, so reconcile considers the rows stuck."""
    with db.connect() as conn:
        conn.execute("UPDATE requests SET created_at = now() - interval '5 minutes' WHERE status = 'filing'")


def _assert_consistent(gl):
    """Never a mismatch: every issue has exactly one pending row pointing at it, and failed rows have no issue."""
    rows = _rows()
    linked = [r for r in rows if r["gitlab_issue_iid"] is not None]
    assert sorted(r["gitlab_issue_iid"] for r in linked) == sorted(gl.issues)
    for row in linked:
        assert row["status"] == "pending"
        assert gitlab_client.idempotency_marker(row["idempotency_key"]) in gl.issues[row["gitlab_issue_iid"]]["description"]
    assert all(r["gitlab_issue_iid"] is None for r in rows if r["status"] == "failed")
    assert not [r for r in rows if r["status"] == "filing"]


def test_crash_before_the_issue_is_created(gl):
    gl.fail_before_create = True
    result = tools.create_access_request(ALEX, "snowflake", "read", REASON)
    assert result["error"] == "gitlab_error"
    [row] = _rows()
    assert row["status"] == "filing" and gl.issues == {}

    assert sync.reconcile(gl) == []  # too recent to be called stuck
    _age_filing_rows()
    assert sync.reconcile(gl) == [row["id"]]
    assert _rows()[0]["status"] == "failed"
    _assert_consistent(gl)

    gl.fail_before_create = False  # a failed request does not block asking again
    assert tools.create_access_request(ALEX, "snowflake", "read", REASON)["ok"]


def test_crash_after_the_issue_is_created(gl):
    gl.fail_after_create = True
    result = tools.create_access_request(ALEX, "snowflake", "read", REASON)
    assert result["error"] == "gitlab_error"
    [row] = _rows()
    assert row["status"] == "filing" and row["gitlab_issue_iid"] is None and len(gl.issues) == 1

    _age_filing_rows()
    sync.reconcile(gl)
    [row] = _rows()
    assert row["status"] == "pending" and row["gitlab_issue_iid"] == 1
    _assert_consistent(gl)
    with db.connect() as conn:
        events = [r["event"] for r in conn.execute("SELECT event FROM audit_log WHERE request_id = %s ORDER BY id", (row["id"],))]
    assert "issue_create_failed" in events and "status_changed" in events


def test_normal_filing_goes_through_filing_to_pending(gl):
    assert tools.create_access_request(ALEX, "snowflake", "read", REASON)["ok"]
    [row] = _rows()
    assert row["status"] == "pending" and row["idempotency_key"] is not None
    _assert_consistent(gl)


def test_eight_simultaneous_identical_requests_file_once(gl):
    barrier = threading.Barrier(8)

    def file(_):
        barrier.wait()
        return tools.create_access_request(ALEX, "snowflake", "read", REASON)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(file, range(8)))
    assert sum(r["ok"] for r in results) == 1
    assert {r["error"] for r in results if not r["ok"]} == {"duplicate_request"}
    assert len(_rows()) == 1 and len(gl.issues) == 1
    _assert_consistent(gl)


def test_database_rejects_a_second_open_request_directly(gl):
    """The partial unique index holds even if application code were skipped."""
    import psycopg

    args = (ALEX, "snowflake", "read", "", "medium", [{"role": "manager", "email": "priya.nair@example.com"}])
    db.insert_request(*args, status="pending")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.insert_request(*args, status="partially_approved")
    db.insert_request(*args, status="rejected")  # closed states do not count

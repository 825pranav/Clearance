"""Approval sync (phase 7) against the dry-run GitLab client."""

from unittest.mock import MagicMock

import pytest

from app import db, gitlab_client, sync, tools

ALEX = "alex.chen@example.com"
REASON = "to investigate the elevated 502 errors on the checkout service since the deploy"


@pytest.fixture
def gl(seeded):
    client = gitlab_client.DryRunGitLab()
    gitlab_client.set_client(client)
    yield client
    gitlab_client.set_client(None)


def _file(system, level, reason=REASON):
    result = tools.create_access_request(ALEX, system, level, reason)
    assert result["ok"], result
    with db.connect() as conn:
        return conn.execute("SELECT * FROM requests WHERE id = %s", (result["request_id"],)).fetchone()


def _status(request_id):
    with db.connect() as conn:
        return conn.execute("SELECT status, approvals FROM requests WHERE id = %s", (request_id,)).fetchone()


def _audit_count(request_id):
    with db.connect() as conn:
        return conn.execute("SELECT count(*) AS n FROM audit_log WHERE request_id = %s AND event = 'status_changed'",
                            (request_id,)).fetchone()["n"]


@pytest.mark.parametrize("system", ["tableau", "snowflake"])  # low, medium
def test_manager_label_approves_low_and_medium(gl, system):
    row = _file(system, "read")
    notify = MagicMock()
    gl.update_labels(row["gitlab_issue_iid"], add=["approved::manager"])
    changes = sync.sync_once(gl, notify)
    assert changes == [{"request_id": row["id"], "from": "pending", "to": "approved"}]
    assert _status(row["id"])["status"] == "approved"
    labels = gl.get_labels(row["gitlab_issue_iid"])
    assert "status::approved" in labels and "status::pending" not in labels
    assert notify.call_args.args[0] == ALEX and "fully approved" in notify.call_args.args[1]


def test_high_risk_stays_partial_with_one_label_and_approves_with_both(gl):
    row = _file("aws-production", "read")
    iid = row["gitlab_issue_iid"]

    gl.update_labels(iid, add=["approved::manager"])
    sync.sync_once(gl)
    assert _status(row["id"]) == {"status": "partially_approved", "approvals": ["manager"]}
    audits = _audit_count(row["id"])

    sync.sync_once(gl)  # the same label seen again on the next poll changes nothing
    assert _status(row["id"])["status"] == "partially_approved"
    assert _audit_count(row["id"]) == audits

    gl.update_labels(iid, add=["approved::owner"])
    sync.sync_once(gl)
    assert _status(row["id"]) == {"status": "approved", "approvals": ["manager", "owner"]}
    assert "status::approved" in gl.get_labels(iid) and "status::partially_approved" not in gl.get_labels(iid)


def test_owner_label_alone_does_not_approve_high_or_low(gl):
    high = _file("aws-production", "read")
    low = _file("figma", "read")
    gl.update_labels(high["gitlab_issue_iid"], add=["approved::owner"])
    gl.update_labels(low["gitlab_issue_iid"], add=["approved::owner"])
    sync.sync_once(gl)
    assert _status(high["id"])["status"] == "partially_approved"
    assert _status(low["id"]) == {"status": "pending", "approvals": ["owner"]}


def test_rejected_label_rejects(gl):
    row = _file("snowflake", "read")
    gl.update_labels(row["gitlab_issue_iid"], add=["rejected"])
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "rejected"
    assert "status::rejected" in gl.get_labels(row["gitlab_issue_iid"])


def test_rejection_wins_over_approvals_seen_in_the_same_poll(gl):
    row = _file("snowflake", "read")
    gl.update_labels(row["gitlab_issue_iid"], add=["approved::manager", "rejected"])
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "rejected"


def test_each_change_writes_an_audit_row(gl):
    row = _file("aws-production", "read")
    before = _audit_count(row["id"])  # filing -> pending
    assert before == 1
    gl.update_labels(row["gitlab_issue_iid"], add=["approved::manager"])
    sync.sync_once(gl)
    gl.update_labels(row["gitlab_issue_iid"], add=["approved::owner"])
    sync.sync_once(gl)
    assert _audit_count(row["id"]) == before + 2


def test_terminal_requests_are_not_polled_again(gl):
    row = _file("tableau", "read")
    gl.update_labels(row["gitlab_issue_iid"], add=["approved::manager"])
    sync.sync_once(gl)
    gl.update_labels(row["gitlab_issue_iid"], add=["rejected"])
    assert sync.sync_once(gl) == []
    assert _status(row["id"])["status"] == "approved"

"""Approval sync (phase 7) against the dry-run GitLab client, including who is allowed to add each label."""

from unittest.mock import MagicMock

import pytest

from app import db, gitlab_client, sync, tools

ALEX = "alex.chen@example.com"
REASON = "to investigate the elevated 502 errors on the checkout service since the deploy"
# Alex's manager is Priya. Owners: Devon (AWS), Lena (Snowflake, Tableau), Kai (Figma).
USERNAMES = {"priya.nair@example.com": "priya", "devon.price@example.com": "devon",
             "lena.fischer@example.com": "lena", "kai.walker@example.com": "kai", "alex.chen@example.com": "alex"}


@pytest.fixture
def gl(seeded):
    with db.connect() as conn:
        for email, username in USERNAMES.items():
            conn.execute("UPDATE employees SET gitlab_username = %s WHERE email = %s", (username, email))
    client = gitlab_client.DryRunGitLab()
    gitlab_client.set_client(client)
    yield client
    gitlab_client.set_client(None)


def _file(system, level, reason=REASON):
    result = tools.create_access_request(ALEX, system, level, reason)
    assert result["ok"], result
    with db.connect() as conn:
        return conn.execute("SELECT * FROM requests WHERE id = %s", (result["request_id"],)).fetchone()


def _label(gl, row, label, by):
    gl.update_labels(row["gitlab_issue_iid"], add=[label], user=by)


def _status(request_id):
    with db.connect() as conn:
        return conn.execute("SELECT status, approvals FROM requests WHERE id = %s", (request_id,)).fetchone()


def _audit(request_id, event):
    with db.connect() as conn:
        return conn.execute("SELECT detail FROM audit_log WHERE request_id = %s AND event = %s ORDER BY id",
                            (request_id, event)).fetchall()


@pytest.mark.parametrize("system", ["tableau", "snowflake"])  # low, medium
def test_manager_label_approves_low_and_medium(gl, system):
    row = _file(system, "read")
    notify = MagicMock()
    _label(gl, row, "approved::manager", by="priya")
    changes = sync.sync_once(gl, notify)
    assert changes == [{"request_id": row["id"], "from": "pending", "to": "approved"}]
    assert _status(row["id"])["status"] == "approved"
    labels = gl.get_labels(row["gitlab_issue_iid"])
    assert "status::approved" in labels and "status::pending" not in labels
    assert notify.call_args.args[0] == ALEX and "fully approved" in notify.call_args.args[1]


def test_high_risk_stays_partial_with_one_label_and_approves_with_both(gl):
    row = _file("aws-production", "read")
    _label(gl, row, "approved::manager", by="priya")
    sync.sync_once(gl)
    assert _status(row["id"]) == {"status": "partially_approved", "approvals": ["manager"]}
    audits = len(_audit(row["id"], "status_changed"))

    sync.sync_once(gl)  # the same label seen again on the next poll changes nothing
    assert _status(row["id"])["status"] == "partially_approved"
    assert len(_audit(row["id"], "status_changed")) == audits

    _label(gl, row, "approved::owner", by="devon")
    sync.sync_once(gl)
    assert _status(row["id"]) == {"status": "approved", "approvals": ["manager", "owner"]}
    labels = gl.get_labels(row["gitlab_issue_iid"])
    assert "status::approved" in labels and "status::partially_approved" not in labels


def test_owner_label_alone_does_not_approve_high_or_low(gl):
    high = _file("aws-production", "read")
    low = _file("figma", "read")
    _label(gl, high, "approved::owner", by="devon")
    _label(gl, low, "approved::owner", by="kai")
    sync.sync_once(gl)
    assert _status(high["id"])["status"] == "partially_approved"
    assert _status(low["id"]) == {"status": "pending", "approvals": []}  # low risk has no owner slot to fill


def test_rejected_label_from_an_approver_rejects(gl):
    row = _file("snowflake", "read")
    _label(gl, row, "rejected", by="priya")
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "rejected"
    assert "status::rejected" in gl.get_labels(row["gitlab_issue_iid"])


def test_rejection_wins_over_approvals_seen_in_the_same_poll(gl):
    row = _file("snowflake", "read")
    _label(gl, row, "approved::manager", by="priya")
    _label(gl, row, "rejected", by="priya")
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "rejected"


def test_each_change_writes_an_audit_row(gl):
    row = _file("aws-production", "read")
    assert len(_audit(row["id"], "status_changed")) == 1  # filing -> pending
    _label(gl, row, "approved::manager", by="priya")
    sync.sync_once(gl)
    _label(gl, row, "approved::owner", by="devon")
    sync.sync_once(gl)
    assert len(_audit(row["id"], "status_changed")) == 3


def test_terminal_requests_are_not_polled_again(gl):
    row = _file("tableau", "read")
    _label(gl, row, "approved::manager", by="priya")
    sync.sync_once(gl)
    _label(gl, row, "rejected", by="priya")
    assert sync.sync_once(gl) == []
    assert _status(row["id"])["status"] == "approved"


# ---------------------------------------------------------------- forged approvals (threat T9)


def test_approval_label_added_by_someone_else_is_ignored(gl):
    row = _file("aws-production", "read")
    _label(gl, row, "approved::owner", by="mallory")
    _label(gl, row, "approved::manager", by="devon")  # a real approver, but in the wrong slot
    assert sync.sync_once(gl) == []
    assert _status(row["id"]) == {"status": "pending", "approvals": []}
    ignored = [a["detail"] for a in _audit(row["id"], "label_ignored")]
    assert {(d["label"], d["added_by"]) for d in ignored} == {("approved::owner", "mallory"), ("approved::manager", "devon")}


def test_requester_cannot_approve_their_own_request(gl):
    row = _file("snowflake", "read")
    _label(gl, row, "approved::manager", by="alex")
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "pending"


def test_rejection_by_a_non_approver_is_ignored(gl):
    row = _file("snowflake", "read")
    _label(gl, row, "rejected", by="mallory")
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "pending"


def test_unmapped_approver_cannot_be_impersonated(gl):
    with db.connect() as conn:
        conn.execute("UPDATE employees SET gitlab_username = NULL WHERE email = 'priya.nair@example.com'")
    row = _file("snowflake", "read")
    _label(gl, row, "approved::manager", by="anyone")
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "pending"


def test_ignored_labels_are_audited_once_not_every_poll(gl):
    row = _file("snowflake", "read")
    _label(gl, row, "approved::manager", by="mallory")
    for _ in range(3):
        sync.sync_once(gl)
    assert len(_audit(row["id"], "label_ignored")) == 1


def test_a_forged_label_replaced_by_the_real_approver_counts(gl):
    row = _file("snowflake", "read")
    _label(gl, row, "approved::manager", by="mallory")
    sync.sync_once(gl)
    gl.update_labels(row["gitlab_issue_iid"], remove=["approved::manager"], user="priya")
    _label(gl, row, "approved::manager", by="priya")
    sync.sync_once(gl)
    assert _status(row["id"])["status"] == "approved"


def test_verified_events_is_a_pure_function():
    usernames = {"manager": "priya", "owner": "devon"}
    labels = ["approved::manager", "approved::owner"]
    assert sync.verified_events(labels, {"approved::manager": "priya", "approved::owner": "devon"}, usernames) == \
        (["manager_approved", "owner_approved"], [])
    assert sync.verified_events(labels, {"approved::manager": "priya", "approved::owner": "priya"}, usernames) == \
        (["manager_approved"], ["approved::owner"])

"""Approval sync: polls GitLab issue labels and moves requests through the state machine.

Approvers record decisions as labels on the issue (`approved::manager`, `approved::owner`, `rejected`).
Every poll replays the labels it sees; `policy.transition` makes the repeats harmless.
Run it on its own with: python -m app.sync
"""

import logging
import sys
import time

from app import config, db, gitlab_client

log = logging.getLogger("clearance.sync")
POLL_SECONDS = 30
STUCK_FILING_SECONDS = 60
LABEL_EVENTS = (("approved::manager", "manager_approved"), ("approved::owner", "owner_approved"))
STATUS_MESSAGES = {
    "partially_approved": "One of the two approvals is in; still waiting on the other.",
    "approved": "It's fully approved. The system owner will now provision your access.",
    "rejected": "It was rejected. Check the issue for the approver's comments.",
    "failed": "The GitLab issue could not be created, so nothing was filed. Please ask again.",
}


def events_from_labels(labels: list[str]) -> list[str]:
    """A rejection wins over any approvals present at the same time."""
    if "rejected" in labels:
        return ["rejected"]
    return [event for label, event in LABEL_EVENTS if label in labels]


def reconcile(gl, older_than_seconds: int = STUCK_FILING_SECONDS) -> list[int]:
    """Repair requests left in `filing` by a crash between the database insert and the GitLab call."""
    repaired = []
    for row in db.requests_stuck_filing(older_than_seconds):
        issue = gl.find_issue(gitlab_client.idempotency_marker(row["idempotency_key"]))
        if issue:
            db.attach_issue(row["id"], issue["iid"], issue["url"])
            db.advance(row["id"], "issue_created", actor="reconcile")
        else:
            db.advance(row["id"], "issue_failed", actor="reconcile")
        repaired.append(row["id"])
    return repaired


def sync_once(gl, notify=None) -> list[dict]:
    """One poll: reconcile stuck filings, then apply label events to every open request."""
    reconcile(gl)
    changes = []
    for row in db.requests_with_status(("pending", "partially_approved")):
        try:
            labels = gl.get_labels(row["gitlab_issue_iid"])
        except Exception:
            log.exception("could not read labels for request %s", row["id"])
            continue
        old_status, new_status = row["status"], row["status"]
        for event in events_from_labels(labels):
            new_status = db.advance(row["id"], event, actor="sync").status
        if new_status == old_status:
            continue
        gl.update_labels(row["gitlab_issue_iid"], add=[f"status::{new_status}"], remove=[f"status::{old_status}"])
        changes.append({"request_id": row["id"], "from": old_status, "to": new_status})
        if notify:
            system = db.resolve_system(row["system_key"])
            text = (f"Update on your {row['access_level']} access request for {system['name']} "
                    f"({row['gitlab_issue_url']}): {STATUS_MESSAGES[new_status]}")
            try:
                notify(row["employee_email"], text)
            except Exception:
                log.exception("could not notify %s", row["employee_email"])
    return changes


def run_forever(gl, notify=None, interval: int = POLL_SECONDS) -> None:
    while True:
        try:
            for change in sync_once(gl, notify):
                log.info("request %(request_id)s: %(from)s -> %(to)s", change)
        except Exception:
            log.exception("sync cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if config.GITLAB_DRY_RUN:
        sys.exit("The standalone sync needs real GitLab (GITLAB_DRY_RUN=0): dry-run issues only exist inside the "
                 "process that created them.")
    notifier = None
    if config.SLACK_BOT_TOKEN:
        from slack_sdk import WebClient

        from app.slack_bot import make_notifier

        notifier = make_notifier(WebClient(token=config.SLACK_BOT_TOKEN))
    run_forever(gitlab_client.get_client(), notifier)

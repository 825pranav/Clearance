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
# (label, event, approver slot whose GitLab user must have added the label)
LABEL_EVENTS = (("approved::manager", "manager_approved", "manager"), ("approved::owner", "owner_approved", "owner"))
STATUS_MESSAGES = {
    "partially_approved": "One of the two approvals is in; still waiting on the other.",
    "approved": "It's fully approved. The system owner will now provision your access.",
    "rejected": "It was rejected. Check the issue for the approver's comments.",
    "failed": "The GitLab issue could not be created, so nothing was filed. Please ask again.",
}


def verified_events(labels: list[str], adders: dict[str, str], usernames: dict[str, str | None]) -> tuple[list[str], list[str]]:
    """Turn issue labels into lifecycle events, counting a label only if the right person added it.

    `adders` maps each label to the GitLab user who added it (from the issue's label history) and `usernames`
    maps each approver slot to that approver's GitLab username. `approved::manager` counts only if the
    manager's account added it, `approved::owner` only if the owner's, and `rejected` if any approver did.
    A rejection wins over approvals seen in the same poll. Returns (events, labels ignored as unverified).
    """
    def added_by(label: str, slots) -> bool:
        allowed = {usernames.get(slot) for slot in slots} - {None}
        return adders.get(label) in allowed

    ignored = []
    if "rejected" in labels:
        if added_by("rejected", usernames):
            return ["rejected"], []
        ignored.append("rejected")
    events = []
    for label, event, slot in LABEL_EVENTS:
        if label not in labels:
            continue
        if added_by(label, [slot]):
            events.append(event)
        else:
            ignored.append(label)
    return events, ignored


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
            adders = gl.label_adders(row["gitlab_issue_iid"])
        except Exception:
            log.exception("could not read labels for request %s", row["id"])
            continue
        usernames = db.approver_gitlab_usernames(row["approvers"])
        events, ignored = verified_events(labels, adders, usernames)
        for label in ignored:  # recorded once, not on every poll
            db.audit_once("label_ignored", "sync", {"label": label, "added_by": adders.get(label),
                                                     "expected": usernames}, request_id=row["id"])
        old_status, new_status = row["status"], row["status"]
        for event in events:
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

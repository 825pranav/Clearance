"""Slack entry point: Bolt in Socket Mode, so no public URL is needed.

Answers direct messages and @mentions in a thread, and runs the approval sync in a background thread.
Run it with: python -m app.slack_bot
"""

import logging
import re
import sys
import threading

from app import config, db, gitlab_client, sync
from app.agent import handle_message

log = logging.getLogger("clearance.slack")
MENTION = re.compile(r"<@[A-Z0-9]+>\s*")
NOT_IN_DIRECTORY = "Sorry, I can't find you in the employee directory, so I can't file access requests for you."


def resolve_employee(client, slack_user_id: str) -> str | None:
    """Slack user -> employee email: stored Slack id, then the Slack profile email, then DEMO_EMPLOYEE_EMAIL."""
    employee = db.get_employee_by_slack_id(slack_user_id)
    if employee:
        return employee["email"]
    try:
        email = client.users_info(user=slack_user_id)["user"]["profile"].get("email")
    except Exception:
        log.exception("users.info failed for %s", slack_user_id)
        email = None
    if email and db.get_employee(email):
        return email
    if config.DEMO_EMPLOYEE_EMAIL and db.get_employee(config.DEMO_EMPLOYEE_EMAIL):
        return config.DEMO_EMPLOYEE_EMAIL
    return None


def on_message(event: dict, client, handle=handle_message) -> None:
    """Handle one DM or mention: work out who is asking, run the agent, reply in the thread."""
    if event.get("bot_id") or event.get("subtype"):
        return  # our own replies, edits and other non-user messages
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    text = MENTION.sub("", event.get("text", "")).strip()
    email = resolve_employee(client, event["user"])
    if email:
        reply = handle(email, f"{channel}:{thread_ts}", text).reply
    else:
        reply = NOT_IN_DIRECTORY
    client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=reply)


def make_notifier(client):
    """Returns notify(email, text), which DMs an employee. Used by the sync job on status changes."""

    def notify(email: str, text: str) -> None:
        employee = db.get_employee(email)
        user_id = (employee or {}).get("slack_user_id") or client.users_lookupByEmail(email=email)["user"]["id"]
        channel = client.conversations_open(users=user_id)["channel"]["id"]
        client.chat_postMessage(channel=channel, text=text)

    return notify


def build_app():
    from slack_bolt import App

    app = App(token=config.SLACK_BOT_TOKEN)

    @app.event("message")
    def direct_message(event, client):
        if event.get("channel_type") == "im":
            on_message(event, client)

    @app.event("app_mention")
    def mention(event, client):
        on_message(event, client)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not config.SLACK_BOT_TOKEN or not config.SLACK_APP_TOKEN:
        sys.exit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set. See HANDOFF.md, 'Finish setup'.")
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = build_app()  # Bolt calls auth.test here, so bad tokens fail fast
    log.info("authenticated as %s", app.client.auth_test()["user"])
    if "--check" in sys.argv:
        return
    gl = gitlab_client.get_client()
    sync.reconcile(gl)  # settle any request a crash left in `filing` before taking new messages
    notify = make_notifier(app.client)
    threading.Thread(target=sync.run_forever, args=(gl, notify), daemon=True).start()
    SocketModeHandler(app, config.SLACK_APP_TOKEN).start()


if __name__ == "__main__":
    main()

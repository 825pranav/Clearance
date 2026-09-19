"""Chat with the agent from the terminal: python -m app.cli [employee_email]

Uses the same handle_message as the Slack bot. With GITLAB_DRY_RUN=1 issues get fake URLs.
"""

import sys
import uuid

from app import config, db
from app.agent import handle_message

DEFAULT_EMPLOYEE = "alex.chen@example.com"


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else (config.DEMO_EMPLOYEE_EMAIL or DEFAULT_EMPLOYEE)
    employee = db.get_employee(email)
    if not employee:
        sys.exit(f"{email} is not in the employees table. Run `make seed` or pass a seeded email.")
    conversation_id = f"cli:{uuid.uuid4().hex[:8]}"
    print(f"Chatting as {employee['name']} ({employee['role']}). GitLab dry run: {config.GITLAB_DRY_RUN}. "
          "Ctrl+C or an empty line to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        result = handle_message(email, conversation_id, text)
        print(f"\nclearance> {result.reply}")
        print(f"[outcome: {result.outcome}" + (f", request #{result.request_id}]" if result.request_id else "]"))


if __name__ == "__main__":
    main()

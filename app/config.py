"""Environment loading. Every setting the app reads comes from here."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# Real environment variables win over .env, so tests and evals can override anything.
load_dotenv(ROOT / ".env", override=False)


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DATABASE_URL = _get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/clearance")

LLM_PROVIDER = _get("LLM_PROVIDER", "openai")  # openai (any compatible endpoint) or anthropic
LLM_BASE_URL = _get("LLM_BASE_URL")
LLM_API_KEY = _get("LLM_API_KEY")
LLM_MODEL = _get("LLM_MODEL")
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")

GITLAB_URL = _get("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN = _get("GITLAB_TOKEN")
GITLAB_PROJECT_ID = _get("GITLAB_PROJECT_ID")
GITLAB_DRY_RUN = _get("GITLAB_DRY_RUN", "1") != "0"

SLACK_BOT_TOKEN = _get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = _get("SLACK_APP_TOKEN")
DEMO_EMPLOYEE_EMAIL = _get("DEMO_EMPLOYEE_EMAIL")

# The console connects with its own limited login when this is set (see app/console_grants.sql).
CONSOLE_DATABASE_URL = _get("CONSOLE_DATABASE_URL")
CONSOLE_DB_PASSWORD = _get("CONSOLE_DB_PASSWORD")
DJANGO_DEBUG = _get("DJANGO_DEBUG", "0") == "1"
DJANGO_SECRET_KEY = _get("DJANGO_SECRET_KEY")
DJANGO_ALLOWED_HOSTS = [host.strip() for host in _get("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()]

HANDBOOK_DIR = ROOT / "data" / "handbook"
INDEX_DIR = Path(_get("INDEX_DIR", str(ROOT / "data" / "index")))
TEMPLATE_PATH = ROOT / "templates" / "access_request.md"

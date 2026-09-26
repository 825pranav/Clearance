"""GitLab access behind one small interface, with a real client and an in-memory dry-run client.

`GITLAB_DRY_RUN=1` selects the dry-run client. Tests and evals always use it, so they never create real issues.
"""

import threading

from app import config


class GitLabError(Exception):
    pass


def idempotency_marker(key) -> str:
    """Hidden text in every issue body that ties the issue to its request row (see sync.reconcile)."""
    return f"clearance-key: {key}"


class DryRunGitLab:
    """Keeps issues in memory and returns fake URLs. Two switches simulate crashes for the D2 tests."""

    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.fail_before_create = False
        self.fail_after_create = False
        self._lock = threading.Lock()

    def create_issue(self, title: str, description: str, labels: list[str]) -> dict:
        if self.fail_before_create:
            raise GitLabError("simulated failure before the issue was created")
        with self._lock:
            iid = len(self.issues) + 1
            url = f"https://gitlab.example.com/dry-run/access-requests/-/issues/{iid}"
            self.issues[iid] = {"iid": iid, "url": url, "title": title, "description": description,
                                "labels": list(labels), "state": "opened"}
        if self.fail_after_create:
            raise GitLabError("simulated crash after the issue was created, before the response arrived")
        return {"iid": iid, "url": url}

    def find_issue(self, text: str) -> dict | None:
        for issue in self.issues.values():
            if text in issue["description"]:
                return {"iid": issue["iid"], "url": issue["url"]}
        return None

    def get_labels(self, iid: int) -> list[str]:
        return list(self.issues[iid]["labels"])

    def update_labels(self, iid: int, add: list[str] = (), remove: list[str] = ()) -> None:
        with self._lock:
            labels = [label for label in self.issues[iid]["labels"] if label not in remove]
            self.issues[iid]["labels"] = labels + [label for label in add if label not in labels]

    def close_issue(self, iid: int) -> None:
        self.issues[iid]["state"] = "closed"


class GitLabClient:
    """The same interface backed by python-gitlab and a real project."""

    def __init__(self, url: str, token: str, project_id: str):
        import gitlab

        if not token or not project_id:
            raise GitLabError("GITLAB_TOKEN and GITLAB_PROJECT_ID must be set when GITLAB_DRY_RUN=0")
        # A short timeout keeps any create call well inside reconcile's 60-second window.
        self._gl = gitlab.Gitlab(url, private_token=token, timeout=20)
        self._project = self._gl.projects.get(project_id)

    def create_issue(self, title: str, description: str, labels: list[str]) -> dict:
        issue = self._project.issues.create({"title": title, "description": description, "labels": labels})
        return {"iid": issue.iid, "url": issue.web_url}

    def find_issue(self, text: str) -> dict | None:
        # Search first; fall back to scanning recent access requests in case search does not index the comment.
        candidates = list(self._project.issues.list(search=text, get_all=True))
        candidates += list(self._project.issues.list(labels=["access-request"], order_by="created_at", per_page=100, get_all=False))
        for issue in candidates:
            if text in (issue.description or ""):
                return {"iid": issue.iid, "url": issue.web_url}
        return None

    def get_labels(self, iid: int) -> list[str]:
        return list(self._project.issues.get(iid).labels)

    def update_labels(self, iid: int, add: list[str] = (), remove: list[str] = ()) -> None:
        issue = self._project.issues.get(iid)
        labels = [label for label in issue.labels if label not in remove]
        issue.labels = labels + [label for label in add if label not in labels]
        issue.save()

    def close_issue(self, iid: int) -> None:
        issue = self._project.issues.get(iid)
        issue.state_event = "close"
        issue.save()


_client = None


def get_client():
    global _client
    if _client is None:
        if config.GITLAB_DRY_RUN:
            _client = DryRunGitLab()
        else:
            _client = GitLabClient(config.GITLAB_URL, config.GITLAB_TOKEN, config.GITLAB_PROJECT_ID)
    return _client


def set_client(client) -> None:
    """Swap the client (tests use this to get a fresh dry-run client)."""
    global _client
    _client = client

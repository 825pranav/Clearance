"""The dashboard script runs end to end against the test database, with and without requests."""

from streamlit.testing.v1 import AppTest

from app import config, gitlab_client, tools

APP = str(config.ROOT / "dashboard" / "app.py")


def test_dashboard_renders_with_no_requests(seeded):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("No requests yet" in info.value for info in at.info)


def test_dashboard_renders_requests_and_audit_trail(seeded):
    gitlab_client.set_client(gitlab_client.DryRunGitLab())
    try:
        assert tools.create_access_request("alex.chen@example.com", "tableau", "read", "")["ok"]
        assert tools.create_access_request("alex.chen@example.com", "aws-production", "read",
                                           "to investigate the elevated 502 errors on the checkout service")["ok"]
    finally:
        gitlab_client.set_client(None)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [s.value for s in at.subheader][:4] == ["By status", "By risk tier", "Requests", "Audit trail"]
    assert len(at.dataframe) >= 2

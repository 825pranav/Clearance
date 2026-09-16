import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app import config, db, gitlab_client, tools

ALEX = "alex.chen@example.com"
JUSTIFICATION = "to investigate the elevated 502 errors on the checkout service since the deploy"


@pytest.fixture
def gl(seeded):
    client = gitlab_client.DryRunGitLab()
    gitlab_client.set_client(client)
    yield client
    gitlab_client.set_client(None)


def _rows(sql, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchall()


def test_valid_request_creates_row_audit_and_issue(gl):
    result = tools.create_access_request(ALEX, "snowflake", "read", "to build the weekly churn report for the finance team",
                                         conversation_id="c1")
    assert result["ok"] and result["risk_tier"] == "medium" and result["status"] == "pending"
    assert result["approvers"] == [{"role": "manager", "name": "Priya Nair"}]

    [row] = _rows("SELECT * FROM requests")
    assert (row["employee_email"], row["system_key"], row["access_level"], row["status"]) == (ALEX, "snowflake", "read", "pending")
    assert row["gitlab_issue_url"] == result["issue_url"]

    events = [(r["event"], r["request_id"], r["conversation_id"]) for r in _rows("SELECT * FROM audit_log ORDER BY id")]
    assert ("request_filed", row["id"], None) in events
    assert ("tool_called", row["id"], "c1") in events

    issue = gl.issues[row["gitlab_issue_iid"]]
    assert issue["title"] == "Access request: Snowflake (read) for Alex Chen"
    assert issue["labels"] == ["access-request", "risk::medium", "status::pending"]
    body = issue["description"]
    for section in ("## Requester", "## System", "## Access level", "## Risk tier", "## Justification",
                    "## Required approvals", "## Policy reference"):
        assert section in body
    assert "Backend Engineer" in body and "Engineering" in body
    assert "- [ ] Manager: Priya Nair (priya.nair@example.com)" in body
    assert "`snowflake.md`: \"Every Snowflake request needs a justification" in body
    assert "cannot grant access" in body


def test_aliases_and_case_resolve_to_the_system_key(gl):
    result = tools.create_access_request(ALEX, "The Data Warehouse", "READ", "to build the weekly churn report for the finance team")
    assert result["ok"]
    assert _rows("SELECT system_key, access_level FROM requests")[0] == {"system_key": "snowflake", "access_level": "read"}


def test_unknown_system_and_level_are_structured_errors(gl):
    assert tools.create_access_request(ALEX, "jira", "read")["error"] == "unknown_system"
    assert tools.create_access_request(ALEX, "figma", "owner")["error"] == "invalid_access_level"
    assert tools.create_access_request("nobody@example.com", "figma", "read")["error"] == "unknown_employee"
    assert _rows("SELECT * FROM requests") == []


def test_baseline_covered_request_is_refused(gl):
    result = tools.create_access_request(ALEX, "aws-sandbox", "read")
    assert result == {**result, "ok": False, "error": "already_has_access", "existing": "baseline"}
    assert _rows("SELECT * FROM requests") == [] and gl.issues == {}


def test_duplicate_of_pending_request_is_refused(gl):
    assert tools.create_access_request(ALEX, "tableau", "write")["ok"]
    result = tools.create_access_request(ALEX, "tableau", "read")
    assert result["error"] == "duplicate_request" and result["existing"] == "open_request"
    assert len(_rows("SELECT * FROM requests")) == 1 and len(gl.issues) == 1


def test_high_risk_with_short_justification_is_refused(gl):
    result = tools.create_access_request(ALEX, "aws-production", "read", "debugging prod issue quickly")
    assert result["error"] == "justification_required"
    assert _rows("SELECT * FROM requests") == []


def test_high_risk_lists_two_distinct_approvers(gl):
    result = tools.create_access_request(ALEX, "aws-production", "read", JUSTIFICATION)
    assert result["ok"] and result["risk_tier"] == "high"
    assert result["approvers"] == [{"role": "manager", "name": "Priya Nair"}, {"role": "owner", "name": "Devon Price"}]
    [row] = _rows("SELECT approvers FROM requests")
    assert len({a["email"] for a in row["approvers"]}) == 2
    assert "risk::high" in gl.issues[1]["labels"]


def test_admin_on_a_low_system_is_high_risk(gl):
    result = tools.create_access_request(ALEX, "figma", "admin", "to move library ownership after the design team restructure")
    assert result["risk_tier"] == "high" and len(result["approvers"]) == 2


def test_requester_without_manager_gets_no_manager_error(gl):
    assert tools.create_access_request("morgan.lee@example.com", "figma", "read")["error"] == "no_manager"


def test_check_existing_access_reports_result_and_risk(gl):
    check = tools.check_existing_access(ALEX, "AWS prod", "read")
    assert check["result"] == "none" and check["risk_tier"] == "high" and check["justification_required"] is True
    assert tools.check_existing_access(ALEX, "gcp-sandbox", "write")["result"] == "baseline"
    assert tools.check_existing_access(ALEX, "figma", "read")["justification_required"] is False


def test_get_employee_and_search_handbook(gl):
    assert tools.get_employee(ALEX) == {"ok": True, "name": "Alex Chen", "role": "Backend Engineer",
                                        "department": "Engineering", "manager": "Priya Nair"}
    results = tools.search_handbook("who approves production access")["results"]
    assert len(results) == 3 and {"source", "heading", "text"} <= set(results[0])
    assert len(_rows("SELECT * FROM audit_log WHERE event = 'tool_called'")) == 2


def test_mcp_server_over_stdio_lists_four_tools_and_searches(seeded):
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"],
                                       env=dict(os.environ), cwd=str(config.ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = (await session.list_tools()).tools
                result = await session.call_tool("search_handbook", {"query": "Snowflake justification"})
                return listed, result

    listed, result = asyncio.run(run())
    assert sorted(t.name for t in listed) == ["check_existing_access", "create_access_request", "get_employee", "search_handbook"]
    payload = json.loads(result.content[0].text)
    assert payload["ok"] and len(payload["results"]) == 3
    assert payload["results"][0]["source"] == "snowflake.md"

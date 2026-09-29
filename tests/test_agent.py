"""The agent loop with a scripted fake LLM and the real MCP tool server. No network needed."""

import json
from types import SimpleNamespace

import pytest

from app import db
from app.agent import MAX_TOOL_ROUNDS, Agent, ToolClient, outcome_from_trace

ALEX = "alex.chen@example.com"


def tool_call(name, **args):
    return SimpleNamespace(id=f"call_{name}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def says(text):
    return SimpleNamespace(content=text, tool_calls=None)


def calls(*tool_calls):
    return SimpleNamespace(content="", tool_calls=list(tool_calls))


class ScriptedLLM:
    """Returns canned messages in order and records what it was sent."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def chat(self, messages, tools=None):
        self.requests.append({"messages": list(messages), "tools": tools})
        return self.script.pop(0) if self.script else says("done")


@pytest.fixture(scope="module")
def tool_client():
    client = ToolClient()
    yield client
    client.close()


def _requests():
    with db.connect() as conn:
        return conn.execute("SELECT * FROM requests").fetchall()


def test_model_never_sees_session_parameters(seeded, tool_client):
    agent = Agent(llm=ScriptedLLM(), tools=tool_client)
    names = {s["function"]["name"] for s in agent.tool_schemas}
    assert names == {"search_handbook", "get_employee", "check_existing_access", "create_access_request"}
    for schema in agent.tool_schemas:
        params = schema["function"]["parameters"]
        assert "employee_email" not in params["properties"] and "conversation_id" not in params["properties"]
        assert "employee_email" not in params.get("required", [])


def test_scripted_request_is_filed_for_the_session_user_only(seeded, tool_client):
    llm = ScriptedLLM(
        calls(tool_call("check_existing_access", system_key="snowflake", access_level="read")),
        # The model tries to file for someone else; the agent drops that argument and uses the session identity.
        calls(tool_call("create_access_request", system_key="snowflake", access_level="read",
                        justification="to build the weekly churn report for the finance team",
                        employee_email="sam.okafor@example.com")),
        says("Filed!"),
    )
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-1", "I need snowflake read for churn")
    assert result.outcome == "filed" and result.reply == "Filed!"
    [row] = _requests()
    assert row["employee_email"] == ALEX and row["id"] == result.request_id
    with db.connect() as conn:
        audited = conn.execute("SELECT count(*) AS n FROM audit_log WHERE event = 'tool_called' AND conversation_id = 'conv-1'").fetchone()
    assert audited["n"] == 2
    assert "sam.okafor" not in json.dumps(result.trace[1]["args"])


def test_baseline_check_gives_already_has(seeded, tool_client):
    llm = ScriptedLLM(calls(tool_call("check_existing_access", system_key="aws-sandbox", access_level="write")),
                      says("Your role already includes that."))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-2", "aws sandbox write please")
    assert (result.outcome, result.request_id) == ("already_has", None)
    assert _requests() == []


def test_loop_stops_after_six_tool_rounds(seeded, tool_client):
    llm = ScriptedLLM(*[calls(tool_call("get_employee")) for _ in range(10)])
    llm.script.insert(MAX_TOOL_ROUNDS, says("Giving up politely."))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-3", "loop forever")
    assert len(llm.requests) == MAX_TOOL_ROUNDS + 1
    assert llm.requests[-1]["tools"] is None
    assert result.reply == "Giving up politely." and result.outcome == "no_action"


def test_malformed_and_unknown_tool_calls_are_reported_back(seeded, tool_client):
    bad = SimpleNamespace(id="x", function=SimpleNamespace(name="check_existing_access", arguments="{not json"))
    llm = ScriptedLLM(calls(bad, tool_call("grant_access", system_key="okta-admin")), says("Sorry."))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-4", "hi")
    assert result.malformed_tool_calls == 2
    assert [step["result"]["error"] for step in result.trace] == ["invalid_arguments", "unknown_tool"]


def test_missing_required_argument_is_explained_to_the_model(seeded, tool_client):
    llm = ScriptedLLM(calls(tool_call("create_access_request", system_key="tableau", access_level="read")), says("ok"))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-9", "tableau read")
    assert result.trace[0]["result"]["error"] == "invalid_arguments"
    assert "justification" in result.trace[0]["result"]["message"]
    assert result.malformed_tool_calls == 1 and _requests() == []


def test_history_is_kept_per_conversation(seeded, tool_client):
    llm = ScriptedLLM(says("Which level?"), says("Thanks."), says("Hello."))
    agent = Agent(llm=llm, tools=tool_client)
    agent.handle_message(ALEX, "conv-5", "I need Tableau")
    agent.handle_message(ALEX, "conv-5", "read")
    agent.handle_message(ALEX, "conv-6", "unrelated")
    second, third = llm.requests[1]["messages"], llm.requests[2]["messages"]
    assert [m["content"] for m in second[1:]] == ["I need Tableau", "Which level?", "read"]
    assert len(third) == 2


def test_system_prompt_lists_the_catalogue(seeded, tool_client):
    prompt = Agent(llm=ScriptedLLM(), tools=tool_client).system_prompt
    assert "aws-production: AWS Production (also called: aws prod" in prompt
    assert "cannot grant" in prompt


def test_claimed_filing_without_a_tool_result_gets_one_correction(seeded, tool_client):
    llm = ScriptedLLM(says("Your request has been filed: https://gitlab.com/fake/1"), says("Which access level do you need?"))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-7", "tableau please")
    assert result.reply == "Which access level do you need?" and result.outcome == "no_action"
    assert "Automatic check" in llm.requests[1]["messages"][-1]["content"]


def test_repeated_false_claim_is_replaced_by_a_safe_reply(seeded, tool_client):
    llm = ScriptedLLM(says("I have filed it."), says("Done, issue link: https://gitlab.com/fake/2"))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-8", "tableau please")
    assert result.reply.startswith("I haven't filed anything yet")
    assert _requests() == []


def test_claimed_access_needs_a_tool_result_behind_it(seeded, tool_client):
    llm = ScriptedLLM(calls(tool_call("check_existing_access", system_key="snowflake", access_level="admin")),
                      says("It looks like you already have admin access to Snowflake."),
                      says("You already have admin access."))
    result = Agent(llm=llm, tools=tool_client).handle_message(ALEX, "conv-10", "admin on snowflake")
    assert result.reply.startswith("I couldn't confirm that you have that access")


def test_true_access_claims_and_hedged_wording_pass_the_check():
    from app.agent import unbacked_claim

    baseline = [{"tool": "check_existing_access", "result": {"ok": True, "result": "baseline"}}]
    assert unbacked_claim("You already have write access through your role.", baseline) is None
    assert unbacked_claim("Let me check if you already have read access.", []) is None
    assert unbacked_claim("You don't currently have read access to Tableau.", []) is None


def test_outcome_comes_from_tool_results_not_text():
    assert outcome_from_trace([]) == ("no_action", None)
    assert outcome_from_trace([{"tool": "check_existing_access", "result": {"ok": True, "result": "open_request"}}]) == ("duplicate", None)
    assert outcome_from_trace([{"tool": "create_access_request",
                                "result": {"ok": False, "error": "already_has_access"}}]) == ("already_has", None)
    assert outcome_from_trace([{"tool": "create_access_request",
                                "result": {"ok": False, "error": "justification_required"}}]) == ("no_action", None)
    assert outcome_from_trace([{"tool": "create_access_request", "result": {"ok": True, "request_id": 7}}]) == ("filed", 7)

"""The Claude backend with a fake Anthropic client: message conversion, thinking-block replay, refusals,
and the full agent loop filing a request. No network or API key needed."""

import json
from types import SimpleNamespace

import pytest

from app import db
from app.agent import Agent, ToolClient
from app.llm import ClaudeLLM

ALEX = "alex.chen@example.com"


def block(type, **fields):
    return SimpleNamespace(type=type, **fields)


def response(*content, stop_reason="end_turn"):
    return SimpleNamespace(content=list(content), stop_reason=stop_reason)


class FakeAnthropic:
    """Records each create() call and returns scripted responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


TOOLS = [{"type": "function", "function": {"name": "get_employee", "description": "Look up the requester.",
                                            "parameters": {"type": "object", "properties": {}}}}]


def test_tool_call_round_trip_replays_thinking_blocks_unchanged():
    thinking = block("thinking", thinking="", signature="sig")
    tool_use = block("tool_use", id="toolu_1", name="get_employee", input={})
    fake = FakeAnthropic(response(thinking, tool_use, stop_reason="tool_use"), response(block("text", text="Hi Alex.")))
    llm = ClaudeLLM(client=fake, model="claude-opus-5-5")

    first = llm.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "who am I"}], TOOLS)
    assert first.content == "" and first.tool_calls[0].function.name == "get_employee"
    assert json.loads(first.tool_calls[0].function.arguments) == {}

    history = [
        {"role": "system", "content": "SYS"}, {"role": "user", "content": "who am I"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "toolu_1", "type": "function",
                                                              "function": {"name": "get_employee", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": '{"ok": true}'},
    ]
    second = llm.chat(history, TOOLS)
    assert second.content == "Hi Alex." and second.tool_calls is None

    sent = fake.requests[1]
    assert sent["system"] == "SYS"
    assert sent["messages"][1] == {"role": "assistant", "content": [thinking, tool_use]}  # the exact blocks, unchanged
    assert sent["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"ok": true}'}]}
    assert "temperature" not in sent and sent["output_config"] == {"effort": "medium"}
    assert sent["fallbacks"] == "default" and sent["betas"] == [ClaudeLLM.FALLBACK_BETA]
    assert sent["tools"][0]["input_schema"] == {"type": "object", "properties": {}}


def test_parallel_tool_results_go_back_in_one_message():
    llm = ClaudeLLM(client=FakeAnthropic(), model="m")
    calls = [{"id": f"t{i}", "type": "function", "function": {"name": "get_employee", "arguments": "{}"}} for i in (1, 2)]
    _, out = llm.convert_messages([
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "checking", "tool_calls": calls},
        {"role": "tool", "tool_call_id": "t1", "content": "a"}, {"role": "tool", "tool_call_id": "t2", "content": "b"},
    ])
    assert [b["type"] for b in out[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["t1", "t2"]


def test_final_round_without_tools_keeps_definitions_and_forbids_calls():
    fake = FakeAnthropic(response(block("tool_use", id="t1", name="get_employee", input={}), stop_reason="tool_use"),
                         response(block("text", text="done")))
    llm = ClaudeLLM(client=fake, model="m")
    llm.chat([{"role": "user", "content": "x"}], TOOLS)
    llm.chat([{"role": "user", "content": "x"}], None)
    assert fake.requests[1]["tool_choice"] == {"type": "none"} and fake.requests[1]["tools"]


def test_refusal_becomes_a_polite_text_reply():
    llm = ClaudeLLM(client=FakeAnthropic(response(stop_reason="refusal")), model="m")
    assert llm.chat([{"role": "user", "content": "x"}]).content == ClaudeLLM.REFUSAL_REPLY


@pytest.fixture(scope="module")
def tool_client():
    client = ToolClient()
    yield client
    client.close()


def test_agent_files_a_request_through_the_claude_backend(seeded, tool_client):
    create = block("tool_use", id="toolu_9", name="create_access_request",
                   input={"system_key": "snowflake", "access_level": "read",
                          "justification": "to build the weekly churn report for the finance team"})
    fake = FakeAnthropic(response(block("thinking", thinking="", signature="s"), create, stop_reason="tool_use"),
                         response(block("text", text="Filed.")))
    result = Agent(llm=ClaudeLLM(client=fake, model="claude-opus-5-5"), tools=tool_client).handle_message(
        ALEX, "claude-1", "snowflake read for the churn report")
    assert result.outcome == "filed"
    with db.connect() as conn:
        row = conn.execute("SELECT employee_email, risk_tier FROM requests").fetchone()
    assert row == {"employee_email": ALEX, "risk_tier": "medium"}
    tool_names = {t["name"] for t in fake.requests[0]["tools"]}
    assert "create_access_request" in tool_names
    assert all("employee_email" not in t["input_schema"]["properties"] for t in fake.requests[0]["tools"])

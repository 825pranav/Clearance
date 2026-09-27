"""The Slack handler with a mocked Slack client: identity, threading and the reply."""

from unittest.mock import MagicMock

import pytest

from app import config, slack_bot
from app.agent import AgentResult


@pytest.fixture
def client():
    mock = MagicMock()
    mock.users_info.return_value = {"user": {"profile": {"email": "alex.chen@example.com"}}}
    return mock


@pytest.fixture
def handle():
    return MagicMock(return_value=AgentResult(reply="Filed: https://gitlab.example.com/1", outcome="filed", request_id=1))


def test_dm_calls_handle_message_and_replies_in_thread(seeded, client, handle):
    event = {"channel": "D123", "channel_type": "im", "user": "U1", "ts": "1700.1", "text": "I need Snowflake read"}
    slack_bot.on_message(event, client, handle=handle)
    handle.assert_called_once_with("alex.chen@example.com", "D123:1700.1", "I need Snowflake read")
    client.chat_postMessage.assert_called_once_with(channel="D123", thread_ts="1700.1", text="Filed: https://gitlab.example.com/1")


def test_reply_inside_an_existing_thread_keeps_the_conversation(seeded, client, handle):
    event = {"channel": "C9", "user": "U1", "ts": "1700.9", "thread_ts": "1700.1", "text": "<@UBOT> read please"}
    slack_bot.on_message(event, client, handle=handle)
    handle.assert_called_once_with("alex.chen@example.com", "C9:1700.1", "read please")
    assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "1700.1"


def test_bot_messages_and_edits_are_ignored(seeded, client, handle):
    slack_bot.on_message({"channel": "D1", "bot_id": "B1", "ts": "1", "text": "hi"}, client, handle=handle)
    slack_bot.on_message({"channel": "D1", "subtype": "message_changed", "ts": "1"}, client, handle=handle)
    handle.assert_not_called()
    client.chat_postMessage.assert_not_called()


def test_unknown_user_without_demo_fallback_is_told_so(seeded, client, handle, monkeypatch):
    monkeypatch.setattr(config, "DEMO_EMPLOYEE_EMAIL", "")
    client.users_info.return_value = {"user": {"profile": {"email": "stranger@elsewhere.com"}}}
    slack_bot.on_message({"channel": "D1", "user": "U2", "ts": "5", "text": "hi"}, client, handle=handle)
    handle.assert_not_called()
    assert client.chat_postMessage.call_args.kwargs["text"] == slack_bot.NOT_IN_DIRECTORY


def test_unknown_user_falls_back_to_demo_employee(seeded, client, handle, monkeypatch):
    monkeypatch.setattr(config, "DEMO_EMPLOYEE_EMAIL", "jordan.reyes@example.com")
    client.users_info.return_value = {"user": {"profile": {"email": "stranger@elsewhere.com"}}}
    slack_bot.on_message({"channel": "D1", "user": "U2", "ts": "5", "text": "hi"}, client, handle=handle)
    assert handle.call_args.args[0] == "jordan.reyes@example.com"


def test_notifier_opens_a_dm_and_posts(seeded, client):
    client.users_lookupByEmail.return_value = {"user": {"id": "U7"}}
    client.conversations_open.return_value = {"channel": {"id": "D7"}}
    slack_bot.make_notifier(client)("alex.chen@example.com", "approved")
    client.conversations_open.assert_called_once_with(users="U7")
    client.chat_postMessage.assert_called_once_with(channel="D7", text="approved")

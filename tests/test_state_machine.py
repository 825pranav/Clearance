"""The request lifecycle (phase D1): example tests plus property tests over random event sequences."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.policy import EVENTS, RISKS, STATES, TERMINAL, IllegalTransition, State, transition

risks = st.sampled_from(RISKS)
event_sequences = st.lists(st.sampled_from(EVENTS), max_size=15)


def walk(events: list[str], risk: str, start: State = State("filing")) -> list[tuple[str | None, State]]:
    """Apply events in order, skipping illegal ones. Returns (event, state after it), starting with (None, start)."""
    path = [(None, start)]
    for event in events:
        try:
            path.append((event, transition(path[-1][1], event, risk)))
        except IllegalTransition:
            pass
    return path


# ---------------------------------------------------------------- examples


def test_filing_becomes_pending_or_failed():
    assert transition(State("filing"), "issue_created", "low") == State("pending")
    assert transition(State("filing"), "issue_failed", "low") == State("failed")


@pytest.mark.parametrize("risk", ["low", "medium"])
def test_manager_approval_approves_low_and_medium(risk):
    assert transition(State("pending"), "manager_approved", risk).status == "approved"


@pytest.mark.parametrize("risk", ["low", "medium"])
def test_owner_approval_alone_does_not_approve_low_and_medium(risk):
    assert transition(State("pending"), "owner_approved", risk) == State("pending", frozenset({"owner"}))


def test_high_risk_needs_two_distinct_approvals():
    one = transition(State("pending"), "manager_approved", "high")
    assert one == State("partially_approved", frozenset({"manager"}))
    assert transition(one, "manager_approved", "high") == one
    assert transition(one, "owner_approved", "high").status == "approved"


def test_rejection_from_any_open_state():
    assert transition(State("pending"), "rejected", "low").status == "rejected"
    assert transition(State("partially_approved", frozenset({"owner"})), "rejected", "high").status == "rejected"


@pytest.mark.parametrize("event", ["manager_approved", "owner_approved", "rejected"])
def test_nothing_can_happen_to_an_issue_that_does_not_exist_yet(event):
    with pytest.raises(IllegalTransition):
        transition(State("filing"), event, "high")


def test_a_filed_request_cannot_fail_and_unknown_events_are_illegal():
    with pytest.raises(IllegalTransition):
        transition(State("pending"), "issue_failed", "low")
    with pytest.raises(IllegalTransition):
        transition(State("pending"), "escalated", "low")


# ---------------------------------------------------------------- properties


@settings(max_examples=500)
@given(risks, event_sequences)
def test_every_reachable_status_is_known(risk, events):
    assert all(state.status in STATES for _, state in walk(events, risk))


@settings(max_examples=500)
@given(event_sequences)
def test_high_risk_never_approved_without_both_approvals(events):
    seen = set()
    for event, state in walk(events, "high"):
        seen.add(event)
        if state.status == "approved":
            assert {"manager_approved", "owner_approved"} <= seen


@settings(max_examples=500)
@given(risks, event_sequences)
def test_terminal_state_never_changes(risk, events):
    path = walk(events, risk)
    for i, (_, state) in enumerate(path):
        if state.status in TERMINAL:
            assert all(later == state for _, later in path[i:])


@settings(max_examples=500)
@given(risks, event_sequences, st.sampled_from(EVENTS))
def test_applying_an_event_twice_equals_applying_it_once(risk, events, event):
    for _, state in walk(events, risk):
        try:
            once = transition(state, event, risk)
        except IllegalTransition:
            continue
        assert transition(once, event, risk) == once


@settings(max_examples=500)
@given(risks, event_sequences)
def test_rejected_always_ends_the_request(risk, events):
    path = walk(events, risk)
    for i in range(1, len(path)):
        event, state = path[i]
        before = path[i - 1][1]
        if event == "rejected" and before.status not in TERMINAL:
            assert state.status == "rejected"
            assert all(later.status == "rejected" for _, later in path[i:])

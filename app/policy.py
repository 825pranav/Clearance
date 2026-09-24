"""Every access policy decision, as pure functions.

Nothing in this module touches the database, the network or the LLM. The tools load the facts
(employee, system, existing requests) and pass them in, so each rule can be unit tested directly.
"""

from dataclasses import dataclass

LEVELS = ("read", "write", "admin")
RISKS = ("low", "medium", "high")
MIN_JUSTIFICATION_WORDS = 8


class PolicyError(Exception):
    """A request that the policy cannot route, such as a requester with no manager on file."""


def level_rank(level: str) -> int:
    """read < write < admin. Raises ValueError for anything else."""
    return LEVELS.index(level)


def covers(held: str, requested: str) -> bool:
    """Holding a level covers every level below it."""
    return level_rank(held) >= level_rank(requested)


def effective_risk(system_risk: str, access_level: str) -> str:
    """Admin on anything is high risk; otherwise the system's own tier applies."""
    if system_risk not in RISKS:
        raise ValueError(f"unknown risk tier: {system_risk}")
    level_rank(access_level)
    return "high" if access_level == "admin" else system_risk


def required_approvers(risk: str, employee: dict, system: dict) -> list[dict]:
    """Who must approve, as [{"role": ..., "email": ...}].

    Low and medium need the requester's manager. High also needs the system owner. Nobody approves
    their own request: when the requester owns the system, their manager stands in for the owner.
    """
    manager = employee.get("manager_email")
    if not manager:
        raise PolicyError(f"{employee['email']} has no manager on file, so nobody can approve the request")
    approvers = [{"role": "manager", "email": manager}]
    if risk == "high":
        owner = system["owner_email"]
        if owner == employee["email"]:
            owner = manager
        approvers.append({"role": "owner", "email": owner})
    return approvers


def validate_justification(risk: str, text: str | None) -> bool:
    """Optional for low risk; medium and high need at least eight words."""
    if risk == "low":
        return True
    return len((text or "").split()) >= MIN_JUSTIFICATION_WORDS


# ---------------------------------------------------------------- request lifecycle

STATES = ("filing", "pending", "partially_approved", "approved", "rejected", "failed")
TERMINAL = ("approved", "rejected", "failed")
OPEN_STATES = ("filing", "pending", "partially_approved")
EVENTS = ("issue_created", "issue_failed", "manager_approved", "owner_approved", "rejected")
APPROVAL_EVENTS = {"manager_approved": "manager", "owner_approved": "owner"}
REQUIRED_APPROVALS = {"low": {"manager"}, "medium": {"manager"}, "high": {"manager", "owner"}}


class IllegalTransition(Exception):
    pass


@dataclass(frozen=True)
class State:
    """A request's status plus the approvals recorded so far.

    The approvals are part of the state because the sync job sees the same labels on every poll: to make a
    repeated `manager_approved` harmless while a different second approval completes a high-risk request,
    the machine has to remember which approvals it already has.
    """

    status: str
    approvals: frozenset = frozenset()


def transition(state: State, event: str, risk: str) -> State:
    """The only way a request's status changes. Pure: same input, same output, no I/O.

    Raises IllegalTransition for events that make no sense in the current state (approving a request whose
    issue does not exist yet, failing a request that was filed). Terminal states ignore every event.
    """
    if event not in EVENTS:
        raise IllegalTransition(f"unknown event {event!r}")
    if state.status in TERMINAL:
        return state
    if event == "issue_created":
        return State("pending", state.approvals) if state.status == "filing" else state
    if event == "issue_failed":
        if state.status != "filing":
            raise IllegalTransition(f"issue_failed in state {state.status}: the issue already exists")
        return State("failed", state.approvals)
    if state.status == "filing":
        raise IllegalTransition(f"{event} in state filing: there is no issue to act on yet")
    if event == "rejected":
        return State("rejected", state.approvals)
    approvals = state.approvals | {APPROVAL_EVENTS[event]}
    required = REQUIRED_APPROVALS[risk]
    if required <= approvals:
        return State("approved", approvals)
    return State("partially_approved" if approvals & required else "pending", approvals)


def existing_access(access_level: str, baseline_level: str | None, requests: list[dict]) -> str:
    """Whether the employee already has, or already asked for, this access.

    `baseline_level` is what the employee's role includes for this system (None if nothing).
    `requests` are the employee's earlier requests for this system, each with `access_level` and `status`.
    Returns "baseline", "already_granted", "open_request" or "none".

    One open request per employee per system, at any level: a second one waits until the first is decided.
    The database enforces the same rule with a partial unique index, so a race cannot get around it.
    """
    if baseline_level and covers(baseline_level, access_level):
        return "baseline"
    if any(r["status"] == "approved" and covers(r["access_level"], access_level) for r in requests):
        return "already_granted"
    if any(r["status"] in OPEN_STATES for r in requests):
        return "open_request"
    return "none"

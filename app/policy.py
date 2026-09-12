"""Every access policy decision, as pure functions.

Nothing in this module touches the database, the network or the LLM. The tools load the facts
(employee, system, existing requests) and pass them in, so each rule can be unit tested directly.
"""

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


def existing_access(access_level: str, baseline_level: str | None, requests: list[dict]) -> str:
    """Whether the employee already has, or already asked for, this access.

    `baseline_level` is what the employee's role includes for this system (None if nothing).
    `requests` are the employee's earlier requests for this system, each with `access_level` and `status`.
    Returns "baseline", "already_granted", "open_request" or "none".
    """
    if baseline_level and covers(baseline_level, access_level):
        return "baseline"
    if any(r["status"] == "approved" and covers(r["access_level"], access_level) for r in requests):
        return "already_granted"
    if any(r["status"] == "pending" and covers(r["access_level"], access_level) for r in requests):
        return "open_request"
    return "none"

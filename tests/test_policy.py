import pytest
import yaml

from app import config, db, policy
from app.policy import PolicyError

ALEX = {"email": "alex.chen@example.com", "role": "Backend Engineer", "manager_email": "priya.nair@example.com"}
DEVON = {"email": "devon.price@example.com", "role": "Engineering Manager", "manager_email": "morgan.lee@example.com"}
MORGAN = {"email": "morgan.lee@example.com", "role": "Engineering Manager", "manager_email": None}
AWS_PROD = {"key": "aws-production", "risk_tier": "high", "owner_email": "devon.price@example.com"}
SNOWFLAKE = {"key": "snowflake", "risk_tier": "medium", "owner_email": "lena.fischer@example.com"}


# ---------------------------------------------------------------- access levels


def test_levels_are_ordered_read_write_admin():
    assert policy.level_rank("read") < policy.level_rank("write") < policy.level_rank("admin")


@pytest.mark.parametrize("held,requested,expected", [
    ("admin", "read", True), ("admin", "write", True), ("write", "read", True),
    ("read", "read", True), ("read", "write", False), ("write", "admin", False),
])
def test_higher_level_covers_lower(held, requested, expected):
    assert policy.covers(held, requested) is expected


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        policy.level_rank("superuser")


# ---------------------------------------------------------------- risk


@pytest.mark.parametrize("tier", ["low", "medium", "high"])
def test_read_and_write_keep_the_system_tier(tier):
    assert policy.effective_risk(tier, "read") == tier
    assert policy.effective_risk(tier, "write") == tier


@pytest.mark.parametrize("tier", ["low", "medium", "high"])
def test_admin_is_always_high(tier):
    assert policy.effective_risk(tier, "admin") == "high"


def test_unknown_risk_tier_is_rejected():
    with pytest.raises(ValueError):
        policy.effective_risk("critical", "read")


# ---------------------------------------------------------------- approvers


@pytest.mark.parametrize("risk", ["low", "medium"])
def test_low_and_medium_need_only_the_manager(risk):
    assert policy.required_approvers(risk, ALEX, SNOWFLAKE) == [{"role": "manager", "email": "priya.nair@example.com"}]


def test_high_needs_manager_and_owner_who_are_distinct():
    approvers = policy.required_approvers("high", ALEX, AWS_PROD)
    assert approvers == [
        {"role": "manager", "email": "priya.nair@example.com"},
        {"role": "owner", "email": "devon.price@example.com"},
    ]
    assert len({a["email"] for a in approvers}) == 2


def test_owner_never_approves_their_own_request():
    approvers = policy.required_approvers("high", DEVON, AWS_PROD)
    assert DEVON["email"] not in {a["email"] for a in approvers}
    assert approvers[1] == {"role": "owner", "email": "morgan.lee@example.com"}


def test_requester_without_manager_cannot_be_routed():
    with pytest.raises(PolicyError):
        policy.required_approvers("low", MORGAN, SNOWFLAKE)


# ---------------------------------------------------------------- justification


def test_low_risk_needs_no_justification():
    assert policy.validate_justification("low", "")
    assert policy.validate_justification("low", None)


@pytest.mark.parametrize("risk", ["medium", "high"])
def test_justification_boundary_at_eight_words(risk):
    assert not policy.validate_justification(risk, "one two three four five six seven")
    assert policy.validate_justification(risk, "one two three four five six seven eight")


def test_whitespace_does_not_count_as_words():
    assert not policy.validate_justification("medium", "   ")
    assert not policy.validate_justification("high", "a  b   c    d")


# ---------------------------------------------------------------- existing access


def test_existing_access_baseline_covers_same_and_lower_levels():
    assert policy.existing_access("write", "write", []) == "baseline"
    assert policy.existing_access("read", "write", []) == "baseline"


def test_existing_access_baseline_does_not_cover_higher_level():
    assert policy.existing_access("admin", "write", []) == "none"


def test_existing_access_already_granted():
    requests = [{"access_level": "write", "status": "approved"}]
    assert policy.existing_access("read", None, requests) == "already_granted"
    assert policy.existing_access("admin", None, requests) == "none"


def test_existing_access_open_request():
    requests = [{"access_level": "read", "status": "pending"}]
    assert policy.existing_access("read", None, requests) == "open_request"


def test_existing_access_ignores_rejected_requests():
    assert policy.existing_access("read", None, [{"access_level": "admin", "status": "rejected"}]) == "none"


def test_existing_access_none():
    assert policy.existing_access("read", None, []) == "none"


# ---------------------------------------------------------------- policy agrees with the frozen eval expectations


def test_eval_expectations_match_policy(seeded):
    """Guards against a wrong eval case: every expected risk and approver list must follow from the rules."""
    cases = yaml.safe_load((config.ROOT / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    for case in cases:
        expect = case["expect"]
        if case["category"] in ("baseline", "duplicate"):
            assert expect["outcome"] in ("already_has", "duplicate"), case["id"]
            continue
        if expect["outcome"] != "filed":
            continue
        employee = db.get_employee(case["employee"])
        system = db.resolve_system(expect["system"])
        risk = policy.effective_risk(system["risk_tier"], expect["access_level"])
        assert risk == expect["risk"], case["id"]
        roles = [a["role"] for a in policy.required_approvers(risk, employee, system)]
        assert roles == expect["approvers"], case["id"]
        level = db.baseline_level(employee["role"], system["key"])
        assert policy.existing_access(expect["access_level"], level, []) == "none", case["id"]

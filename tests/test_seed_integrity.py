"""Checks that the seed data, handbook and eval files agree with each other and with the spec."""

from collections import Counter

import pytest
import yaml

from app import config, db

EVALS = config.ROOT / "evals"


def _load(name):
    return yaml.safe_load((EVALS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seed_data():
    db.reset()
    with db.connect() as conn:
        employees = {r["email"]: r for r in conn.execute("SELECT * FROM employees")}
        systems = {r["key"]: r for r in conn.execute("SELECT * FROM systems")}
        baseline = {(r["role"], r["system_key"]): r["access_level"] for r in conn.execute("SELECT * FROM role_baseline")}
    return employees, systems, baseline


def test_ten_systems_with_spec_risk_tiers(seed_data):
    _, systems, _ = seed_data
    expected = {
        "aws-sandbox": "low", "gcp-sandbox": "low", "figma": "low", "tableau": "low",
        "snowflake": "medium", "salesforce": "medium", "zendesk": "medium",
        "aws-production": "high", "gcp-production": "high", "okta-admin": "high",
    }
    assert {k: s["risk_tier"] for k, s in systems.items()} == expected
    for system in systems.values():
        assert 2 <= len(system["aliases"]) <= 3


def test_every_manager_and_owner_exists(seed_data):
    employees, systems, _ = seed_data
    for employee in employees.values():
        if employee["manager_email"] is not None:
            assert employee["manager_email"] in employees
    for system in systems.values():
        assert system["owner_email"] in employees


def test_every_system_has_a_handbook_file(seed_data):
    _, systems, _ = seed_data
    handbook = {p.name for p in config.HANDBOOK_DIR.glob("*.md")}
    assert len(handbook) == 12
    assert {"access-request-process.md", "least-privilege.md"} <= handbook
    for system in systems.values():
        assert system["handbook_doc"] in handbook


def test_spec_minimum_baselines(seed_data):
    _, _, baseline = seed_data
    assert baseline[("Backend Engineer", "aws-sandbox")] == "write"
    assert baseline[("Backend Engineer", "gcp-sandbox")] == "write"
    assert baseline[("Data Analyst", "snowflake")] == "read"
    assert baseline[("Data Analyst", "tableau")] == "read"
    assert baseline[("Support Agent", "zendesk")] == "write"
    assert baseline[("Designer", "figma")] == "write"
    assert baseline[("Sales Ops", "salesforce")] == "write"


def test_owners_differ_from_typical_requesters_managers(seed_data):
    employees, systems, _ = seed_data
    managers = {e["manager_email"] for e in employees.values() if e["role"] not in ("Engineering Manager", "IT Admin", "Operations Manager")}
    assert not managers & {s["owner_email"] for s in systems.values()}


def test_eval_files_only_name_things_that_exist(seed_data):
    employees, systems, _ = seed_data
    handbook = {p.name for p in config.HANDBOOK_DIR.glob("*.md")}
    for case in _load("cases.yaml") + _load("adversarial.yaml"):
        assert case["employee"] in employees, case["id"]
        for row in case.get("setup", []):
            assert row["system"] in systems, case["id"]
        expect = case.get("expect", {})
        if "system" in expect:
            assert expect["system"] in systems, case["id"]
        for name in expect.get("cites", []):
            assert name in handbook, case["id"]
        for allowed in case.get("allowed_requests", []):
            assert allowed["system"] in systems, case["id"]
        if "poison" in case:
            assert case["poison"]["source"] in handbook, case["id"]
    for case in _load("retrieval_cases.yaml"):
        assert case["expected"] in handbook


def test_main_case_counts_match_spec():
    cases = _load("cases.yaml")
    assert len(cases) == 30
    assert len({c["id"] for c in cases}) == 30
    assert Counter(c["category"] for c in cases) == {
        "clear": 10, "vague": 4, "baseline": 3, "duplicate": 3, "high_risk": 4, "policy": 3, "adversarial": 3,
    }
    smoke = [c for c in cases if c.get("smoke")]
    assert len(smoke) == 5
    assert {c["expect"]["outcome"] for c in smoke} == {"filed", "already_has", "duplicate", "no_action"}
    for case in cases:
        if "turn_outcomes" in case["expect"]:
            assert len(case["expect"]["turn_outcomes"]) == len(case["turns"]), case["id"]


def test_adversarial_and_retrieval_counts_match_spec():
    adversarial = _load("adversarial.yaml")
    assert len(adversarial) == 12
    assert Counter(c["category"] for c in adversarial) == {
        "direct_override": 3, "false_authority": 3, "impersonation": 3, "poisoned_document": 3,
    }
    for case in adversarial:
        assert ("poison" in case) == (case["category"] == "poisoned_document"), case["id"]
    assert len(_load("retrieval_cases.yaml")) == 15

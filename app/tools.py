"""The four tools the agent can call. Each returns a plain dict and writes a `tool_called` audit row.

Errors come back as {"ok": False, "error": <code>, "message": ...} instead of exceptions, so the LLM can
read them and react. All policy decisions are made here and in policy.py, never by the caller.
"""

from app import config, db, gitlab_client, policy, retrieval


def _record(tool: str, args: dict, result: dict, conversation_id: str) -> dict:
    """Write the `tool_called` audit row and pass the result through."""
    detail = {"tool": tool, "args": args, "ok": result.get("ok"), "error": result.get("error")}
    db.audit("tool_called", "agent", detail, conversation_id=conversation_id or None, request_id=result.get("request_id"))
    return result


def _error(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": code, "message": message, **extra}


def _name(email: str) -> str:
    employee = db.get_employee(email)
    return employee["name"] if employee else email


def _assess(employee: dict, system: dict, access_level: str) -> tuple[str, dict]:
    """Run the existing-access check and describe the result in a sentence."""
    level = db.baseline_level(employee["role"], system["key"])
    earlier = db.requests_for(employee["email"], system["key"])
    result = policy.existing_access(access_level, level, earlier)
    name = system["name"]
    if result == "baseline":
        message = f"The {employee['role']} role already includes {level} access to {name}, which covers {access_level}. No request is needed."
        return result, {"message": message}
    if result in ("already_granted", "open_request"):
        status = "approved" if result == "already_granted" else "pending"
        match = next(r for r in reversed(earlier) if r["status"] == status and policy.covers(r["access_level"], access_level))
        if result == "already_granted":
            message = f"Request #{match['id']} for {match['access_level']} access to {name} was already approved, which covers {access_level}."
        else:
            message = f"Request #{match['id']} for {match['access_level']} access to {name} is already open and waiting for approval."
        return result, {"message": message, "request_id": match["id"], "issue_url": match["gitlab_issue_url"]}
    return result, {"message": f"No existing {access_level} access to {name}. A new request can be filed."}


def _policy_reference(system: dict) -> tuple[str, str]:
    """The handbook file and the first sentence of its justification section, for the issue body."""
    chunks = retrieval.chunk_markdown(config.HANDBOOK_DIR / system["handbook_doc"])
    chunk = next((c for c in chunks if c["heading"].lower().startswith("justification")), chunks[0])
    return system["handbook_doc"], chunk["text"].split(". ")[0].rstrip(".") + "."


def _render_issue(employee: dict, system: dict, access_level: str, justification: str, risk: str,
                  approvers: list[dict]) -> tuple[str, str]:
    checklist = "\n".join(f"- [ ] {a['role'].capitalize()}: {_name(a['email'])} ({a['email']})" for a in approvers)
    source, snippet = _policy_reference(system)
    body = config.TEMPLATE_PATH.read_text(encoding="utf-8").format(
        employee_name=employee["name"], employee_role=employee["role"], employee_department=employee["department"],
        employee_email=employee["email"], system_name=system["name"], system_key=system["key"],
        access_level=access_level, risk_tier=risk,
        justification=justification or "_Not required for low-risk requests._",
        approvals_checklist=checklist, policy_source=source, policy_snippet=snippet,
    )
    title = f"Access request: {system['name']} ({access_level}) for {employee['name']}"
    return title, body


def _validate(employee_email: str, system_key: str, access_level: str):
    """Shared input checks. Returns (employee, system, level) or an error dict."""
    employee = db.get_employee(employee_email)
    if not employee:
        return _error("unknown_employee", f"{employee_email} is not in the employee directory.")
    system = db.resolve_system(system_key or "")
    if not system:
        keys = ", ".join(s["key"] for s in db.list_systems())
        return _error("unknown_system", f"'{system_key}' is not a known system. Valid system keys: {keys}.")
    level = (access_level or "").strip().lower()
    if level not in policy.LEVELS:
        return _error("invalid_access_level", f"'{access_level}' is not an access level. Use read, write or admin.")
    return employee, system, level


# ---------------------------------------------------------------- tools
# `employee_email` and `conversation_id` are session parameters: the agent hides them from the LLM and
# fills them in from the session, so the model cannot choose who a request is for.


def search_handbook(query: str, conversation_id: str = "") -> dict:
    """Search the access policy handbook. Returns the 3 most relevant sections with their source file and heading."""
    result = {"ok": True, "results": retrieval.search_handbook(query, k=3),
              "note": "When you answer from these results, name the source file you used, e.g. (source: least-privilege.md)."}
    return _record("search_handbook", {"query": query}, result, conversation_id)


def get_employee(employee_email: str, conversation_id: str = "") -> dict:
    """Look up the requester in the employee directory: name, role, department and manager."""
    employee = db.get_employee(employee_email)
    if not employee:
        result = _error("unknown_employee", f"{employee_email} is not in the employee directory.")
    else:
        manager = db.get_employee(employee["manager_email"]) if employee["manager_email"] else None
        result = {"ok": True, "name": employee["name"], "role": employee["role"], "department": employee["department"],
                  "manager": manager["name"] if manager else None}
    return _record("get_employee", {"employee_email": employee_email}, result, conversation_id)


def check_existing_access(employee_email: str, system_key: str, access_level: str, conversation_id: str = "") -> dict:
    """Check whether the requester already has this access through their role, an approved request, or an
    open request, without filing anything. Use it when someone asks whether they have access.
    create_access_request runs the same check itself before filing."""
    args = {"employee_email": employee_email, "system_key": system_key, "access_level": access_level}
    checked = _validate(employee_email, system_key, access_level)
    if isinstance(checked, dict):
        return _record("check_existing_access", args, checked, conversation_id)
    employee, system, level = checked
    result, info = _assess(employee, system, level)
    risk = policy.effective_risk(system["risk_tier"], level)
    needs_reason = not policy.validate_justification(risk, "")
    if result == "none":
        info["next_step"] = ("If they asked for this access, call create_access_request with their reason, if they "
                             "gave one, as the justification.")
    result = {"ok": True, "result": result, "system_key": system["key"], "access_level": level, "risk_tier": risk,
              "justification_required": needs_reason, **info}
    return _record("check_existing_access", args, result, conversation_id)


def create_access_request(employee_email: str, system_key: str, access_level: str, justification: str = "",
                          conversation_id: str = "") -> dict:
    """File an access request as a GitLab issue for the requester. Call it as soon as they have asked for access
    and you know the system and access level. It checks existing access first and refuses if they already have
    it or already have an open request. If the risk tier needs a reason and none was given, it returns the error
    justification_required, and only then should you ask why they need the access. `justification` is the
    requester's own reason in their own words, or empty if they gave none. Risk tier and approvers are decided
    by policy, not by the caller."""
    args = {"employee_email": employee_email, "system_key": system_key, "access_level": access_level,
            "justification": justification}
    result = _file_request(employee_email, system_key, access_level, justification)
    return _record("create_access_request", args, result, conversation_id)


def _file_request(employee_email: str, system_key: str, access_level: str, justification: str) -> dict:
    checked = _validate(employee_email, system_key, access_level)
    if isinstance(checked, dict):
        return checked
    employee, system, level = checked
    justification = (justification or "").strip()

    result, info = _assess(employee, system, level)
    if result in ("baseline", "already_granted"):
        return _error("already_has_access", info["message"], existing=result)
    if result == "open_request":
        return _error("duplicate_request", info["message"], existing=result, issue_url=info["issue_url"])

    risk = policy.effective_risk(system["risk_tier"], level)
    try:
        approvers = policy.required_approvers(risk, employee, system)
    except policy.PolicyError as exc:
        return _error("no_manager", str(exc))
    if not policy.validate_justification(risk, justification):
        return _error("justification_required",
                      f"This is a {risk}-risk request, so it needs a justification of at least "
                      f"{policy.MIN_JUSTIFICATION_WORDS} words. Ask the requester why they need it; "
                      "the reason must be in their own words, never written for them.")

    title, body = _render_issue(employee, system, level, justification, risk, approvers)
    try:
        issue = gitlab_client.get_client().create_issue(title, body, ["access-request", f"risk::{risk}", "status::pending"])
    except Exception as exc:
        return _error("gitlab_error", f"The GitLab issue could not be created: {exc}")
    request_id = db.insert_request(employee["email"], system["key"], level, justification, risk, approvers)
    db.set_request_issue(request_id, issue["iid"], issue["url"])
    db.audit("request_filed", "agent", {"issue_url": issue["url"], "risk_tier": risk}, request_id=request_id)
    return {"ok": True, "request_id": request_id, "issue_url": issue["url"], "risk_tier": risk, "status": "pending",
            "approvers": [{"role": a["role"], "name": _name(a["email"])} for a in approvers]}

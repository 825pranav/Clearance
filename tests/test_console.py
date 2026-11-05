"""The Django console: who can see what, what nobody can change, and that it stays in step with schema.sql."""

import os
import subprocess
import sys

import django
import psycopg
import pytest

django.setup()

from django.contrib.admin.utils import quote  # noqa: E402
from django.contrib.auth.models import Group, User  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext, setup_test_environment  # noqa: E402
from django.urls import reverse  # noqa: E402

from app import config, db  # noqa: E402
from console.models import AuditLog, Employee, Request, ReadOnlyError, RoleBaseline, System  # noqa: E402

ALEX = "alex.chen@example.com"
APPROVERS = [{"role": "manager", "email": "priya.nair@example.com"}]


@pytest.fixture(scope="session", autouse=True)
def _console_tables(_test_database):
    setup_test_environment()
    call_command("migrate", verbosity=0)
    call_command("setup_roles", verbosity=0)


@pytest.fixture(autouse=True)
def _no_leftover_users():
    yield
    User.objects.all().delete()


def login(role=None, superuser=False):
    user = User.objects.create_user(f"user{User.objects.count()}", password="unused", is_staff=True,
                                    is_superuser=superuser)
    if role:
        user.groups.add(Group.objects.get(name=role))
    client = Client()
    client.force_login(user)
    return client


def file_request(email=ALEX, system="tableau", status="pending"):
    return db.insert_request(email, system, "read", "", "low", APPROVERS, status=status)


def change_url(model, key):
    return reverse(f"admin:console_{model}_change", args=[quote(key)])


def system_form(**overrides):
    return {"name": "Tableau", "aliases": "tableau server", "risk_tier": "low", "owner": "lena.fischer@example.com",
            "_save": "Save", **overrides}


def employee_form(**overrides):
    return {"name": "Alex Chen", "role": "Backend Engineer", "department": "Engineering",
            "manager": "priya.nair@example.com", "_save": "Save", **overrides}


# ---------------------------------------------------------------- who can see the console


@pytest.mark.parametrize("path", ["/", "/admin/", "/admin/console/request/", "/admin/console/auditlog/"])
def test_anonymous_visitors_are_sent_to_login(seeded, path):
    response = Client().get(path)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_staff_without_a_role_cannot_see_requests(seeded):
    client = login()
    assert client.get("/").status_code == 403
    assert client.get("/admin/console/request/").status_code == 403


def test_auditor_sees_the_overview_and_request_list(seeded):
    request_id = file_request()
    client = login("Auditor")
    page = client.get("/")
    assert page.status_code == 200
    assert f"#{request_id}" in page.content.decode()
    assert client.get("/admin/console/request/").status_code == 200
    assert client.get(change_url("request", request_id)).status_code == 200


def test_overview_renders_with_no_requests(seeded):
    page = login("Auditor").get("/").content.decode()
    assert "No open requests." in page and "No requests yet." in page


def test_request_page_shows_its_audit_trail(seeded):
    request_id = file_request(status="filing")
    db.advance(request_id, "issue_created", actor="sync")
    assert "status_changed" in login("Auditor").get(change_url("request", request_id)).content.decode()


def test_only_http_issue_links_are_rendered(seeded):
    request_id = file_request()
    db.attach_issue(request_id, 7, "javascript:alert(1)")
    assert "javascript:alert" not in login("Auditor").get("/admin/console/request/").content.decode()


# ---------------------------------------------------------------- nothing here can approve anything


def test_not_even_a_superuser_can_change_a_request(seeded):
    request_id = file_request()
    response = login(superuser=True).post(change_url("request", request_id), {"status": "approved", "_save": "Save"})
    assert response.status_code == 403
    assert Request.objects.get(pk=request_id).status == "pending"


@pytest.mark.parametrize("model", ["request", "auditlog", "employee", "system"])
def test_not_even_a_superuser_can_add_rows(seeded, model):
    assert login(superuser=True).get(reverse(f"admin:console_{model}_add")).status_code == 403


def test_not_even_a_superuser_can_delete_rows(seeded):
    request_id = file_request()
    client = login(superuser=True)
    assert client.post(reverse("admin:console_request_delete", args=[request_id]), {"post": "yes"}).status_code == 403
    assert client.post(reverse("admin:console_system_delete", args=["tableau"]), {"post": "yes"}).status_code == 403
    assert Request.objects.filter(pk=request_id).exists() and System.objects.filter(pk="tableau").exists()


def test_the_models_refuse_writes_even_outside_the_admin(seeded):
    db.audit("note", "test", request_id=file_request())
    request, entry = Request.objects.get(), AuditLog.objects.get()
    for write in (request.save, request.delete, entry.save, entry.delete):
        with pytest.raises(ReadOnlyError):
            write()


# ---------------------------------------------------------------- catalogue edits


def test_auditor_cannot_edit_the_catalogue(seeded):
    response = login("Auditor").post(change_url("system", "tableau"), system_form(risk_tier="high"))
    assert response.status_code == 403
    assert System.objects.get(pk="tableau").risk_tier == "low"


def test_catalogue_edit_is_saved_and_audited(seeded):
    client = login("Catalogue editor")
    username = User.objects.get().username
    response = client.post(change_url("system", "tableau"), system_form(risk_tier="high"))
    assert response.status_code == 302, response.content.decode()
    assert db.resolve_system("tableau")["risk_tier"] == "high"  # the agent's own query sees the edit
    entry = AuditLog.objects.get(event="catalogue_changed")
    assert entry.actor == f"console:{username}"
    assert entry.detail["table"] == "systems" and entry.detail["key"] == "tableau"
    assert entry.detail["changes"]["risk_tier"] == {"from": "low", "to": "high"}


def test_saving_without_changes_writes_no_audit_entry(seeded):
    system = System.objects.get(pk="tableau")
    aliases = ",".join(system.aliases)
    response = login("Catalogue editor").post(change_url("system", "tableau"), system_form(aliases=aliases))
    assert response.status_code == 302
    assert not AuditLog.objects.filter(event="catalogue_changed").exists()


def test_a_primary_key_cannot_be_rewritten_by_a_form(seeded):
    login("Catalogue editor").post(change_url("system", "tableau"), system_form(key="renamed"))
    assert System.objects.filter(pk="tableau").exists() and not System.objects.filter(pk="renamed").exists()


def test_editor_cannot_set_the_identity_fields(seeded):
    response = login("Catalogue editor").post(
        change_url("employee", ALEX), employee_form(department="Platform", gitlab_username="attacker", slack_user_id="U1"))
    assert response.status_code == 302, response.content.decode()
    alex = Employee.objects.get(pk=ALEX)
    assert alex.department == "Platform"
    assert alex.gitlab_username is None and alex.slack_user_id is None


def test_superuser_can_set_the_identity_fields_and_it_is_audited(seeded):
    response = login(superuser=True).post(change_url("employee", ALEX), employee_form(gitlab_username="alexc"))
    assert response.status_code == 302, response.content.decode()
    assert Employee.objects.get(pk=ALEX).gitlab_username == "alexc"
    assert AuditLog.objects.get(event="catalogue_changed").detail["changes"]["gitlab_username"]["to"] == "alexc"


def test_blank_slack_id_stays_null_so_the_unique_constraint_holds(seeded):
    client = login(superuser=True)
    for email, name in ((ALEX, "Alex Chen"), ("sam.okafor@example.com", "Sam Okafor")):
        response = client.post(change_url("employee", email), employee_form(name=name, slack_user_id=""))
        assert response.status_code == 302, response.content.decode()
    assert Employee.objects.get(pk=ALEX).slack_user_id is None


def test_nobody_can_become_their_own_manager(seeded):
    response = login("Catalogue editor").post(change_url("employee", ALEX), employee_form(manager=ALEX))
    assert response.status_code == 200
    assert "cannot be their own manager" in response.content.decode()
    assert Employee.objects.get(pk=ALEX).manager_id == "priya.nair@example.com"


def test_system_page_lists_role_baselines(seeded):
    page = login("Auditor").get(change_url("system", "snowflake")).content.decode()
    assert "Data Analyst: read" in page


# ---------------------------------------------------------------- staying in step with the rest of the app


@pytest.mark.parametrize("model", [Employee, System, RoleBaseline, Request, AuditLog])
def test_models_match_the_columns_in_schema_sql(seeded, model):
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", [model._meta.db_table])
        database = {row[0] for row in cursor.fetchall()}
    assert {field.column for field in model._meta.concrete_fields if field.column} == database


# ---------------------------------------------------------------- the database login itself


@pytest.fixture
def as_console(seeded):
    """Run SQL with exactly the privileges of the console's database login."""
    call_command("migrate", verbosity=0)
    with db.connect() as conn:
        conn.execute(db.CONSOLE_GRANTS.read_text(encoding="utf-8"))
        conn.execute("SET ROLE clearance_console")
        yield conn
        conn.execute("RESET ROLE")


@pytest.mark.parametrize("statement", [
    "UPDATE requests SET status = 'approved'",
    "INSERT INTO requests (employee_email, system_key, access_level, risk_tier, approvers, status) "
    "VALUES ('alex.chen@example.com', 'tableau', 'admin', 'low', '[]', 'approved')",
    "DELETE FROM requests",
    "UPDATE audit_log SET actor = 'someone else'",
    "DELETE FROM audit_log",
    "TRUNCATE audit_log",
    "UPDATE role_baseline SET access_level = 'admin'",
    "INSERT INTO employees (email, name, role, department) VALUES ('x@example.com', 'X', 'Y', 'Z')",
    "DELETE FROM employees",
    "UPDATE employees SET email = 'x@example.com'",
    "INSERT INTO systems (key, name, risk_tier, owner_email, handbook_doc) "
    "VALUES ('x', 'X', 'low', 'alex.chen@example.com', 'x.md')",
    "DELETE FROM systems",
    "UPDATE systems SET key = 'x'",
    "DROP TABLE requests",
])
def test_postgres_refuses_what_the_console_must_never_do(as_console, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_console.execute(statement)


@pytest.mark.parametrize("statement", [
    "SELECT count(*) FROM requests",
    "SELECT count(*) FROM role_baseline",
    "UPDATE systems SET risk_tier = 'high' WHERE key = 'tableau'",
    "UPDATE employees SET department = 'Platform' WHERE email = 'alex.chen@example.com'",
    "INSERT INTO audit_log (actor, event) VALUES ('console:test', 'catalogue_changed')",
    "SELECT count(*) FROM django_session",
    "DELETE FROM django_session",
    "SELECT count(*) FROM auth_user",
])
def test_the_console_login_can_still_do_its_job(as_console, statement):
    as_console.execute(statement)


def test_reseeding_restores_the_console_grants(seeded):
    db.reset()
    with db.connect() as conn:
        conn.execute("SET ROLE clearance_console")
        assert conn.execute("SELECT count(*) AS n FROM systems").fetchone()["n"] == 10
        conn.execute("RESET ROLE")


def test_reseeding_keeps_logins(seeded):
    client = login("Auditor")
    db.reset()
    assert client.get("/").status_code == 200


def test_setup_roles_can_run_twice():
    call_command("setup_roles", verbosity=0)
    assert Group.objects.get(name="Auditor").permissions.count() == 4
    assert Group.objects.get(name="Catalogue editor").permissions.count() == 6


@pytest.mark.parametrize("path", ["/", "/admin/console/request/"])
def test_query_count_does_not_grow_with_requests(seeded, path):
    client = login("Auditor")
    file_request()
    with CaptureQueriesContext(connection) as one:
        assert client.get(path).status_code == 200
    for email in ("sam.okafor@example.com", "jordan.reyes@example.com", "casey.martin@example.com"):
        for system in ("figma", "zendesk", "salesforce"):
            file_request(email, system)
    with CaptureQueriesContext(connection) as many:
        assert client.get(path).status_code == 200
    assert len(many) == len(one)


def test_production_settings_refuse_to_start_without_a_secret_key():
    env = {**os.environ, "DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": ""}
    result = subprocess.run([sys.executable, "-c", "import web.settings"], cwd=config.ROOT, env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr

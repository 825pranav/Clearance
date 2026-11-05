"""Django models over the tables that app/schema.sql owns.

Every model is unmanaged: schema.sql stays the source of truth, Django never creates or alters these tables,
and tests/test_console.py fails if the columns here drift from the real ones. Allowed values come from
app.policy, so the console cannot disagree with the rules.

Requests are read-only and the audit log is insert-only. A request's status changes in exactly one place,
db.advance(), driven by GitLab labels that sync has checked against the approver's account. A write path here
would be a second way to approve something, without that check.
"""

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Now

from app import policy

LEVEL_CHOICES = [(level, level) for level in policy.LEVELS]
RISK_CHOICES = [(risk, risk) for risk in policy.RISKS]
STATUS_CHOICES = [(state, state.replace("_", " ")) for state in policy.STATES]


class ReadOnlyError(Exception):
    """Something tried to write a row that the console may only read."""


class Employee(models.Model):
    email = models.CharField(primary_key=True)
    name = models.CharField()
    role = models.CharField()
    department = models.CharField()
    manager = models.ForeignKey("self", models.PROTECT, db_column="manager_email", null=True, blank=True,
                                related_name="reports")
    slack_user_id = models.CharField(null=True, blank=True, unique=True)
    gitlab_username = models.CharField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "employees"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        # required_approvers() routes a request to the manager, so this would let someone approve their own access.
        if self.manager_id == self.email:
            raise ValidationError({"manager": "An employee cannot be their own manager."})


class System(models.Model):
    key = models.CharField(primary_key=True)
    name = models.CharField()
    aliases = ArrayField(models.CharField(), default=list, blank=True)
    risk_tier = models.CharField(choices=RISK_CHOICES)
    owner = models.ForeignKey(Employee, models.PROTECT, db_column="owner_email", related_name="owned_systems")
    handbook_doc = models.CharField()

    class Meta:
        managed = False
        db_table = "systems"
        ordering = ["key"]

    def __str__(self):
        return self.name


class RoleBaseline(models.Model):
    pk = models.CompositePrimaryKey("role", "system")
    role = models.CharField()
    system = models.ForeignKey(System, models.PROTECT, db_column="system_key", related_name="baselines")
    access_level = models.CharField(choices=LEVEL_CHOICES)

    class Meta:
        managed = False
        db_table = "role_baseline"


class Request(models.Model):
    id = models.BigAutoField(primary_key=True)
    employee = models.ForeignKey(Employee, models.PROTECT, db_column="employee_email", related_name="requests")
    system = models.ForeignKey(System, models.PROTECT, db_column="system_key", related_name="requests")
    access_level = models.CharField(choices=LEVEL_CHOICES)
    justification = models.TextField(blank=True)
    risk_tier = models.CharField(choices=RISK_CHOICES)
    approvers = models.JSONField()
    status = models.CharField(choices=STATUS_CHOICES)
    approvals = ArrayField(models.CharField(), default=list)
    idempotency_key = models.UUIDField(null=True, unique=True)
    gitlab_issue_iid = models.IntegerField(null=True)
    gitlab_issue_url = models.CharField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "requests"
        ordering = ["-id"]

    def __str__(self):
        return f"#{self.id} {self.system_id} ({self.access_level})"

    def save(self, *args, **kwargs):
        raise ReadOnlyError("Requests change only through db.advance().")

    def delete(self, *args, **kwargs):
        raise ReadOnlyError("Requests are never deleted from the console.")


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    conversation_id = models.CharField(null=True)
    request = models.ForeignKey(Request, models.PROTECT, null=True, related_name="audit_entries")
    actor = models.CharField()
    event = models.CharField()
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "audit_log"
        ordering = ["-id"]
        verbose_name = "audit entry"
        verbose_name_plural = "audit log"

    def __str__(self):
        return f"{self.event} by {self.actor}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ReadOnlyError("Audit entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ReadOnlyError("Audit entries cannot be deleted.")

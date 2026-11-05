"""The admin screens. Requests and the audit log can be read but never changed here.

Employees and systems can be edited, because they are the catalogue people need to maintain, but they cannot be
added or deleted, and every edit writes an audit entry in the same transaction. The two fields that decide who
someone is to the other systems (slack_user_id, gitlab_username) are for superusers only: setting your own GitLab
account on an approver would make your labels count as that approver's.
"""

from django.contrib import admin
from django.utils.html import format_html, format_html_join

from console.models import AuditLog, Employee, Request, RoleBaseline, System

IDENTITY_FIELDS = ("slack_user_id", "gitlab_username")


class ReadOnlyAdmin(admin.ModelAdmin):
    """Viewable by anyone with the view permission, changeable by nobody, superusers included."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CatalogueAdmin(admin.ModelAdmin):
    """Edit existing rows only, and record each edit in audit_log."""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Compare real values: form.changed_data flags array fields even when they are identical.
        changes = {}
        for name in form.changed_data:
            before, after = form.initial.get(name), getattr(obj, obj._meta.get_field(name).attname)
            if before != after:
                changes[name] = {"from": before, "to": after}
        if changes:  # the admin runs this view in a transaction, so the edit and its audit row commit together
            AuditLog.objects.create(actor=f"console:{request.user.get_username()}", event="catalogue_changed",
                                    detail={"table": obj._meta.db_table, "key": str(obj.pk), "changes": changes})


class AuditInline(admin.TabularInline):
    model = AuditLog
    fields = readonly_fields = ("created_at", "actor", "event", "detail")
    ordering = ("id",)
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Request)
class RequestAdmin(ReadOnlyAdmin):
    list_display = ("id", "created_at", "employee", "system", "access_level", "risk_tier", "status", "issue_link")
    list_filter = ("status", "risk_tier", "access_level", "system")
    list_select_related = ("employee", "system")
    search_fields = ("employee__name", "employee__email", "system__name", "justification")
    date_hierarchy = "created_at"
    inlines = [AuditInline]

    @admin.display(description="Issue")
    def issue_link(self, obj):
        url = obj.gitlab_issue_url or ""
        if not url.startswith(("https://", "http://")):
            return "-"
        return format_html('<a href="{}" rel="noopener">#{}</a>', url, obj.gitlab_issue_iid)


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "actor", "event", "request")
    list_filter = ("event",)
    list_select_related = ("request",)
    search_fields = ("actor", "event")
    date_hierarchy = "created_at"


@admin.register(Employee)
class EmployeeAdmin(CatalogueAdmin):
    list_display = ("name", "email", "role", "department", "manager")
    list_filter = ("department", "role")
    list_select_related = ("manager",)
    search_fields = ("name", "email", "role")

    def get_readonly_fields(self, request, obj=None):
        return ("email",) if request.user.is_superuser else ("email", *IDENTITY_FIELDS)


@admin.register(System)
class SystemAdmin(CatalogueAdmin):
    list_display = ("key", "name", "risk_tier", "owner")
    list_filter = ("risk_tier",)
    list_select_related = ("owner",)
    search_fields = ("key", "name")
    readonly_fields = ("key", "handbook_doc", "role_baselines")

    # Django's admin cannot register a model with a composite primary key, so baselines are shown here instead.
    @admin.display(description="Included in role baselines")
    def role_baselines(self, obj):
        rows = RoleBaseline.objects.filter(system=obj).order_by("role")
        return format_html_join(", ", "{}: {}", ((row.role, row.access_level) for row in rows)) or "-"

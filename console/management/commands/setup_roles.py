"""Create the console's two roles. Safe to run repeatedly: each group ends up with exactly these permissions."""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

VIEW = ["view_request", "view_auditlog", "view_employee", "view_system"]
ROLES = {
    "Auditor": VIEW,
    "Catalogue editor": [*VIEW, "change_employee", "change_system"],
}


class Command(BaseCommand):
    help = "Create the Auditor and Catalogue editor groups."

    def handle(self, *args, **options):
        for name, codenames in ROLES.items():
            permissions = Permission.objects.filter(content_type__app_label="console", codename__in=codenames)
            if permissions.count() != len(codenames):
                raise SystemExit("Console permissions are missing. Run `python manage.py migrate` first.")
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
            self.stdout.write(f"{name}: {len(codenames)} permissions")

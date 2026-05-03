from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.common.backups.restore import raise_if_core_restore_invalid, validate_core_restore


class Command(BaseCommand):
    help = "Validate account, billing, invitation, and entitlement relationships after a core restore."

    def handle(self, *args, **options):
        errors = validate_core_restore()
        if errors:
            raise_if_core_restore_invalid()
        self.stdout.write(self.style.SUCCESS("Core restore validation passed."))

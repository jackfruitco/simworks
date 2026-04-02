import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from config.settings_parsers import bool_from_env

DEV_EMAIL = "dev@medsim.local"
DEV_PASSWORD = "dev"
DEV_PRODUCT = "medsim_one"
DEV_ROLE = "System"


class Command(BaseCommand):
    help = (
        "Create or update the legacy dev user by delegating to create_demo_user. "
        "Only runs when DJANGO_CREATE_DEV_USER=true and DJANGO_DEBUG=true, "
        "unless --force is provided."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="Bypass DJANGO_DEBUG and DJANGO_CREATE_DEV_USER checks.",
        )

    def handle(self, *args, **options):
        force = options.get("force", False)

        if not force and not bool_from_env("DJANGO_DEBUG"):
            self.stdout.write(self.style.WARNING("Skipped: DJANGO_DEBUG is not enabled."))
            return

        if not force and not bool_from_env("DJANGO_CREATE_DEV_USER"):
            self.stdout.write(self.style.WARNING("Skipped: DJANGO_CREATE_DEV_USER is not enabled."))
            return

        if User.objects.filter(email=DEV_EMAIL).exists():
            self.stdout.write(self.style.WARNING(f"Dev user already exists: {DEV_EMAIL}"))
            return

        password = os.getenv("DJANGO_DEV_USER_PASSWORD", DEV_PASSWORD)

        try:
            call_command(
                "create_demo_user",
                email=DEV_EMAIL,
                password=password,
                product=DEV_PRODUCT,
                role=DEV_ROLE,
                first_name="Dev",
                last_name="User",
                staff=True,
                superuser=True,
                source_ref="manual-entitlement",
                stdout=self.stdout,
                stderr=self.stderr,
            )
        except CommandError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))

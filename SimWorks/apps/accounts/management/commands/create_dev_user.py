import os

from django.core.management.base import BaseCommand

from config.settings_parsers import bool_from_env

DEV_EMAIL = "dev@medsim.local"
DEV_PASSWORD = "dev"


class Command(BaseCommand):
    help = (
        "Create a dev user (dev@medsim.local) if it does not exist. "
        "Only runs when DJANGO_CREATE_DEV_USER=true and DJANGO_DEBUG=true."
    )

    def handle(self, *args, **options):
        from apps.accounts.models import User, UserRole

        if not bool_from_env("DJANGO_DEBUG"):
            self.stdout.write(self.style.WARNING("Skipped: DJANGO_DEBUG is not enabled."))
            return

        if not bool_from_env("DJANGO_CREATE_DEV_USER"):
            self.stdout.write(self.style.WARNING("Skipped: DJANGO_CREATE_DEV_USER is not enabled."))
            return

        role = UserRole.objects.order_by("id").first()
        if role is None:
            self.stdout.write(
                self.style.ERROR(
                    "No UserRole found — cannot create dev user. "
                    "Run migrations or create a role first."
                )
            )
            return

        password = os.getenv("DJANGO_DEV_USER_PASSWORD", DEV_PASSWORD)

        user, created = User.objects.get_or_create(
            email=DEV_EMAIL,
            defaults={
                "first_name": "Dev",
                "last_name": "User",
                "is_active": True,
                "is_staff": True,
                "is_superuser": True,
                "role": role,
            },
        )

        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(
                self.style.SUCCESS(f"Created dev user: {DEV_EMAIL} (role: {role})")
            )
        else:
            self.stdout.write(self.style.WARNING(f"Dev user already exists: {DEV_EMAIL}"))

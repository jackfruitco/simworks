import json

from apps.accounts.models import User
from apps.accounts.models import UserRole
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Restore selected users from a JSON file with preserved passwords and roles (but new IDs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "filepath", type=str, help="Path to the JSON file with user data"
        )

    def handle(self, *args, **options):
        filepath = options["filepath"]

        with open(filepath, "r") as file:
            data = json.load(file)

        for obj in data:
            fields = obj["fields"]
            email = fields["email"]

            if User.objects.filter(email=email).exists():
                self.stdout.write(
                    self.style.WARNING(f"User '{email}' already exists. Skipping.")
                )
                continue

            role_id = fields.get("role")
            if not role_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"User '{email}' missing role. Assigning default role ID 1."
                    )
                )
                role_id = 1  # fallback; replace with a sensible default ID or logic

            try:
                role = UserRole.objects.get(id=role_id)
            except UserRole.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f"Role ID {role_id} not found for '{email}', skipping user."
                    )
                )
                continue

            user = User(
                email=email,
                first_name=fields.get("first_name", ""),
                last_name=fields.get("last_name", ""),
                is_active=fields.get("is_active", True),
                is_staff=fields.get("is_staff", False),
                is_superuser=fields.get("is_superuser", False),
                date_joined=fields.get("date_joined"),
                last_login=fields.get("last_login"),
                password=fields["password"],  # Preserves hash
                role=role,  # required!
            )
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"Created user: {email} with role '{role}'")
            )

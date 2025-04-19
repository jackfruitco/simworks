import json
from django.core.management.base import BaseCommand
from accounts.models import CustomUser, UserRole


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
            username = fields["username"]

            if CustomUser.objects.filter(username=username).exists():
                self.stdout.write(self.style.WARNING(f"User '{username}' already exists. Skipping."))
                continue

            role_id = fields.get("role")
            if not role_id:
                self.stdout.write(
                    self.style.WARNING(f"User '{username}' missing role. Assigning default role ID 1."))
                role_id = 1  # fallback; replace with a sensible default ID or logic

            try:
                role = UserRole.objects.get(id=role_id)
            except UserRole.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Role ID {role_id} not found for '{username}', skipping user."))
                continue

            user = CustomUser(
                username=username,
                email=fields.get("email", ""),
                is_active=fields.get("is_active", True),
                is_staff=fields.get("is_staff", False),
                is_superuser=fields.get("is_superuser", False),
                date_joined=fields.get("date_joined"),
                last_login=fields.get("last_login"),
                password=fields["password"],  # Preserves hash
                role=role,  # required!
            )
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created user: {username} with role '{role}'"))
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

            user = CustomUser(
                username=username,
                email=fields.get("email", ""),
                is_active=fields.get("is_active", True),
                is_staff=fields.get("is_staff", False),
                is_superuser=fields.get("is_superuser", False),
                date_joined=fields.get("date_joined"),
                last_login=fields.get("last_login"),
                password=fields["password"],  # Preserves hash
            )
            user.save()

            role_id = fields.get("role")
            if role_id:
                try:
                    role = UserRole.objects.get(id=role_id)
                    user.role = role
                    user.save(update_fields=["role"])
                    self.stdout.write(self.style.SUCCESS(f"Assigned role '{role}' to '{username}'"))
                except UserRole.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f"Role ID {role_id} not found for '{username}'"))

            self.stdout.write(self.style.SUCCESS(f"Created user: {username}"))
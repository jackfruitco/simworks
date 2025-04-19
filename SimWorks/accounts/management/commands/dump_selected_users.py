import json
from django.core.management.base import BaseCommand
from accounts.models import CustomUser


class Command(BaseCommand):
    help = "Dump selected users into a JSON file (preserving password hashes and roles)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--usernames",
            nargs="+",
            type=str,
            help="List of usernames to include in the dump",
            required=True,
        )
        parser.add_argument(
            "--output",
            type=str,
            default="selected_users.json",
            help="Output filename (default: selected_users.json)",
        )

    def handle(self, *args, **options):
        usernames = options["usernames"]
        output_file = options["output"]

        users = CustomUser.objects.filter(username__in=usernames)
        model_label = f"{CustomUser._meta.app_label}.{CustomUser._meta.model_name}"
        if not users.exists():
            self.stdout.write(self.style.ERROR("No matching users found."))
            return

        user_data = []

        for user in users:
            data = {
                "model": model_label,
                "fields": {
                    "username": user.username,
                    "email": user.email,
                    "password": user.password,  # hashed
                    "is_active": user.is_active,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                    "date_joined": user.date_joined.isoformat(),
                    "role": user.role.id if user.role else None,
                },
            }
            user_data.append(data)

        with open(output_file, "w") as f:
            json.dump(user_data, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"{len(user_data)} user(s) dumped to {output_file}"))
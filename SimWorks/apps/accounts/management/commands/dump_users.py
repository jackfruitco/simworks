import json

from apps.accounts.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Dump users into a JSON file (preserving password hashes and roles)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--emails",
            nargs="+",
            type=str,
            help="List of emails to include in the dump (default: all users). Separate multiple emails with spaces. Use '__ALL__' to include all users.",
            default="__ALL__",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="users.json",
            help="Output filename (default: users.json)",
        )

    def handle(self, *args, **options):
        emails = options["emails"] or "__ALL__"
        output_file = options["output"]

        if emails.upper() == "__ALL__":
            users = User.objects.all()
        else:
            users = User.objects.filter(email__in=emails)

        model_label = f"{User._meta.app_label}.{User._meta.model_name}"
        if not users.exists():
            self.stdout.write(self.style.ERROR("No matching users found."))
            return

        user_data = []

        for user in users:
            data = {
                "model": model_label,
                "fields": {
                    "email": user.email,
                    "password": user.password,  # hashed
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_active": user.is_active,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "last_login": (
                        user.last_login.isoformat() if user.last_login else None
                    ),
                    "date_joined": user.date_joined.isoformat(),
                    "role": user.role.id if user.role else None,
                },
            }
            user_data.append(data)

        with open(output_file, "w") as f:
            json.dump(user_data, f, indent=2)

        self.stdout.write(
            self.style.SUCCESS(f"{len(user_data)} user(s) dumped to {output_file}")
        )

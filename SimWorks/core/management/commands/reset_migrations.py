import os
import sys
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = "Deletes all migration files except __init__.py in all apps."

    def add_arguments(self, parser):
        parser.add_argument(
            "--makemigrations", "-m",
            action="store_true",
            help="Also run makemigrations after deleting migration files."
        )

    def handle(self, *args, **kwargs):
        project_root = Path(__file__).resolve().parent.parent.parent.parent

        deleted_files = []
        for app_path in project_root.iterdir():
            migrations_dir = app_path / "migrations"
            if migrations_dir.exists() and migrations_dir.is_dir():
                for file in migrations_dir.iterdir():
                    if file.name != "__init__.py" and file.suffix == ".py":
                        file.unlink()
                        deleted_files.append(str(file))

        if deleted_files:
            self.stdout.write(self.style.SUCCESS("Deleted migration files:\n" + "\n".join(deleted_files)))
        else:
            self.stdout.write(self.style.WARNING("No migration files found to delete."))

        if kwargs.get("makemigrations"):
            self.stdout.write(self.style.WARNING("Running makemigrations..."))
            call_command("makemigrations")
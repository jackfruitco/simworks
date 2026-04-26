from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sync lab modifier definitions from YAML into the database."

    def add_arguments(self, parser):
        parser.add_argument("--lab", required=True, help="Lab type (e.g. chatlab)")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite DB rows even if manually_edited=True",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report planned changes without writing",
        )

    def handle(self, *args, **options):
        from apps.simcore.modifiers.syncer import sync_lab_modifiers

        lab = options["lab"]
        dry_run = options["dry_run"]
        force = options["force"]

        try:
            summary = sync_lab_modifiers(lab, force=force, dry_run=dry_run)
        except Exception as exc:
            raise CommandError(f"Failed to sync modifiers for {lab!r}: {exc}") from exc

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}Synced modifiers for {lab}: {summary}"))

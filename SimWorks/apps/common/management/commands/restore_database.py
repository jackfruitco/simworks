from __future__ import annotations

from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.common.backups.config import (
    get_postgres_connection_info,
    get_r2_settings,
    get_required_env,
)
from apps.common.backups.inventory import BACKUP_MODES
from apps.common.backups.manifest import (
    parse_manifest,
    sha256_file,
    validate_manifest,
    validate_migration_compatibility,
)
from apps.common.backups.postgres import age_decrypt, pg_restore, zstd_decompress
from apps.common.backups.restore import (
    check_no_business_data,
    expire_pending_invitations_after_restore,
    truncate_core_tables,
)
from apps.common.backups.storage import R2Storage


class Command(BaseCommand):
    help = "Restore an encrypted PostgreSQL logical backup from R2."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=BACKUP_MODES, required=True)
        parser.add_argument("--backup-key", required=True)
        parser.add_argument("--require-empty-db", action="store_true")
        parser.add_argument("--truncate-managed-tables", action="store_true")
        parser.add_argument("--preserve-pending-invitations", action="store_true")
        parser.add_argument("--skip-post-restore-check", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        mode = options["mode"]
        backup_key_arg = options["backup_key"]
        dry_run = options["dry_run"]
        connection_info = get_postgres_connection_info()
        storage = R2Storage(get_r2_settings())

        manifest = self._resolve_manifest(storage, backup_key_arg)
        validate_manifest(manifest, expected_mode=mode)
        validate_migration_compatibility(manifest)
        backup_key = manifest["backup_key"]

        self.stdout.write(f"Restore {'dry run' if dry_run else 'started'}: mode={mode}")
        self.stdout.write(f"Backup object key: {backup_key}")
        self.stdout.write(f"Manifest object key: {manifest['manifest_key']}")

        with tempfile.TemporaryDirectory(prefix="medsim-restore-") as tmpdir_raw:
            tmpdir = Path(tmpdir_raw)
            encrypted_path = tmpdir / "restore.dump.zst.age"
            compressed_path = tmpdir / "restore.dump.zst"
            dump_path = tmpdir / "restore.dump"

            storage.download_file(key=backup_key, path=encrypted_path)
            actual_checksum = sha256_file(encrypted_path)
            if actual_checksum != manifest["sha256"]:
                raise CommandError("Encrypted backup checksum verification failed.")
            if encrypted_path.stat().st_size != int(manifest["size_bytes"]):
                raise CommandError("Encrypted backup size verification failed.")
            self.stdout.write("Encrypted backup checksum verified.")

            if dry_run:
                self.stdout.write(self.style.SUCCESS("Restore dry run completed successfully."))
                return

            private_key = get_required_env("BACKUP_AGE_PRIVATE_KEY")
            age_decrypt(encrypted_path, compressed_path, private_key)
            zstd_decompress(compressed_path, dump_path)

            if mode == "core":
                business_check = check_no_business_data()
                if business_check.has_business_data and not options["truncate_managed_tables"]:
                    tables = ", ".join(business_check.non_empty_tables)
                    raise CommandError(
                        "Refusing to restore into a database with existing business data. "
                        f"Non-empty tables: {tables or 'none'}; "
                        f"non-seed users: {business_check.non_seed_user_count}. "
                        "Re-run with --truncate-managed-tables for a destructive restore."
                    )
                truncate_core_tables()

            pg_restore(connection_info=connection_info, input_path=dump_path)

            if mode == "core" and not options["preserve_pending_invitations"]:
                expired_count = expire_pending_invitations_after_restore()
                self.stdout.write(f"Expired pending invitations after restore: {expired_count}")

            if mode == "core" and not options["skip_post_restore_check"]:
                call_command("check_core_restore")

        self.stdout.write(self.style.SUCCESS("Restore completed successfully."))

    def _resolve_manifest(self, storage: R2Storage, backup_key: str) -> dict:
        if backup_key.endswith(("/latest.json", "latest.json")):
            pointer = parse_manifest_pointer(storage.get_bytes(backup_key))
            return parse_manifest(storage.get_bytes(pointer["manifest_key"]))
        if backup_key.endswith(".manifest.json"):
            return parse_manifest(storage.get_bytes(backup_key))
        if backup_key.endswith(".dump.zst.age"):
            manifest_key = backup_key.removesuffix(".dump.zst.age") + ".manifest.json"
            manifest = parse_manifest(storage.get_bytes(manifest_key))
            if manifest["backup_key"] != backup_key:
                raise CommandError("Manifest backup key does not match requested backup object.")
            return manifest
        raise CommandError("Backup key must point to latest.json, a manifest, or an encrypted dump.")


def parse_manifest_pointer(raw: bytes) -> dict:
    import json

    pointer = json.loads(raw.decode("utf-8"))
    if "manifest_key" not in pointer:
        raise CommandError("Latest pointer does not contain a manifest_key.")
    return pointer

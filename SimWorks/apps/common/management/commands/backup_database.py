from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError

from apps.common.backups.config import (
    get_backup_environment,
    get_postgres_connection_info,
    get_r2_settings,
    get_required_env,
)
from apps.common.backups.inventory import (
    BACKUP_ADVISORY_LOCK_ID,
    BACKUP_MODES,
    assert_core_inventory_safe,
    inventory_for_mode,
)
from apps.common.backups.manifest import (
    build_manifest,
    keys_for_backup,
    manifest_json,
    sha256_file,
)
from apps.common.backups.postgres import (
    age_encrypt,
    backup_advisory_lock,
    pg_dump,
    zstd_compress,
)
from apps.common.backups.storage import R2Storage


class Command(BaseCommand):
    help = "Create an encrypted PostgreSQL logical backup and optionally upload it to R2."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=BACKUP_MODES, required=True)
        parser.add_argument("--upload", choices=("r2", "none"), default="r2")
        parser.add_argument("--encrypt", action="store_true")
        parser.add_argument("--verify-upload", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        mode = options["mode"]
        upload = options["upload"]
        dry_run = options["dry_run"]

        assert_core_inventory_safe()
        inventory = inventory_for_mode(mode)
        connection_info = get_postgres_connection_info()
        environment = get_backup_environment()
        created_at = datetime.now(UTC)
        keys = keys_for_backup(environment, mode, created_at)

        if dry_run:
            self.stdout.write(f"Backup dry run for mode: {mode}")
            self.stdout.write(f"Environment: {environment}")
            self.stdout.write(f"Database: {connection_info.dbname}")
            self.stdout.write(f"Advisory lock key: {BACKUP_ADVISORY_LOCK_ID}")
            self.stdout.write(f"Backup object key: {keys.backup_key}")
            self.stdout.write(f"Manifest object key: {keys.manifest_key}")
            self.stdout.write(f"Latest pointer key: {keys.latest_key}")
            if inventory.tables:
                self.stdout.write("Tables:")
                for table in inventory.tables:
                    self.stdout.write(f"  - {table}")
            else:
                self.stdout.write("Tables: all database tables")
            return

        if not options["encrypt"]:
            raise CommandError("Backups must be encrypted. Re-run with --encrypt.")
        public_key = get_required_env("BACKUP_AGE_PUBLIC_KEY")
        storage = None
        if upload == "r2":
            storage = R2Storage(get_r2_settings())

        self.stdout.write(f"Backup started: mode={mode} environment={environment}")
        if inventory.tables:
            self.stdout.write("Core tables included: " + ", ".join(inventory.tables))

        with (
            backup_advisory_lock(),
            tempfile.TemporaryDirectory(prefix="medsim-backup-") as tmpdir_raw,
        ):
            tmpdir = Path(tmpdir_raw)
            dump_path = tmpdir / f"{mode}.dump"
            compressed_path = tmpdir / f"{mode}.dump.zst"
            encrypted_path = tmpdir / f"{mode}.dump.zst.age"
            manifest_path = tmpdir / f"{mode}.manifest.json"

            pg_dump(
                connection_info=connection_info,
                output_path=dump_path,
                tables=inventory.tables,
                data_only=mode == "core",
            )
            zstd_compress(dump_path, compressed_path)
            age_encrypt(compressed_path, encrypted_path, public_key)

            checksum = sha256_file(encrypted_path)
            size_bytes = encrypted_path.stat().st_size
            manifest = build_manifest(
                mode=mode,
                environment=environment,
                database_name=connection_info.dbname,
                tables=inventory.tables,
                keys=keys,
                sha256=checksum,
                size_bytes=size_bytes,
                created_at=created_at,
            )
            manifest_path.write_bytes(manifest_json(manifest))

            if storage:
                storage.upload_file(
                    path=encrypted_path,
                    key=keys.backup_key,
                    metadata={"sha256": checksum, "backup-mode": mode},
                )
                storage.upload_file(
                    path=manifest_path,
                    key=keys.manifest_key,
                    content_type="application/json",
                )
                storage.put_json(
                    key=keys.latest_key,
                    payload={
                        "backup_key": keys.backup_key,
                        "manifest_key": keys.manifest_key,
                        "created_at": manifest["created_at"],
                        "backup_type": mode,
                        "sha256": checksum,
                        "size_bytes": size_bytes,
                    },
                )
                if options["verify_upload"] and not storage.object_matches(
                    key=keys.backup_key,
                    size_bytes=size_bytes,
                    sha256=checksum,
                ):
                    raise CommandError("R2 upload verification failed for backup object.")
                if options["verify_upload"] and not storage.object_matches(
                    key=keys.manifest_key,
                    size_bytes=manifest_path.stat().st_size,
                ):
                    raise CommandError("R2 upload verification failed for manifest object.")
                self.stdout.write(f"Uploaded backup object: {keys.backup_key}")
                self.stdout.write(f"Uploaded manifest object: {keys.manifest_key}")
            else:
                self.stdout.write(f"Backup artifact written: {encrypted_path}")
                self.stdout.write(f"Manifest written: {manifest_path}")

        self.stdout.write(self.style.SUCCESS("Backup completed successfully."))

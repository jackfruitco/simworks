from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import ClassVar

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
import pytest

from apps.accounts.models import Account, Invitation, User, UserRole
from apps.common.backups.config import get_postgres_connection_info
from apps.common.backups.inventory import (
    CORE_BACKUP_TABLES,
    CORE_FORBIDDEN_TABLES,
)
from apps.common.backups.manifest import (
    build_manifest,
    keys_for_backup,
    sha256_file,
    validate_migration_compatibility,
)
from apps.common.backups.postgres import backup_advisory_lock, pg_dump
from apps.common.backups.restore import (
    FullRestoreEmptinessCheck,
    check_no_business_data,
    expire_pending_invitations_after_restore,
    reseed_table_sequences,
)
from apps.common.backups.storage import R2Storage

POSTGRES_DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "medsim",
        "USER": "appuser",
        "PASSWORD": "super-secret-db-password",
        "HOST": "db",
        "PORT": "5432",
    }
}


def build_test_manifest(mode: str, encrypted: Path, *, migration_heads=None):
    keys = keys_for_backup("production", mode, datetime(2026, 5, 3, 12, 0, tzinfo=UTC))
    return build_manifest(
        mode=mode,
        environment="production",
        database_name="medsim",
        tables=CORE_BACKUP_TABLES if mode == "core" else (),
        keys=keys,
        sha256=sha256_file(encrypted),
        size_bytes=encrypted.stat().st_size,
        created_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        migration_heads=migration_heads or {"accounts": "0001_initial"},
    )


def configure_fake_r2_env(monkeypatch):
    monkeypatch.setenv("BACKUP_R2_BUCKET", "bucket")
    monkeypatch.setenv("BACKUP_R2_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("BACKUP_R2_ACCESS_KEY_ID", "read-key")
    monkeypatch.setenv("BACKUP_R2_SECRET_ACCESS_KEY", "read-secret")


class FakeStorage:
    manifest: ClassVar[dict] = {}
    encrypted_payload = b""

    def __init__(self, settings):
        pass

    def get_bytes(self, key):
        return json.dumps(self.manifest).encode()

    def download_file(self, *, key, path):
        Path(path).write_bytes(self.encrypted_payload)


def test_core_allowlist_excludes_runtime_and_audit_tables():
    assert "django_session" not in CORE_BACKUP_TABLES
    assert "accounts_accountauditevent" not in CORE_BACKUP_TABLES
    assert "accounts_invitationauditevent" not in CORE_BACKUP_TABLES
    assert "billing_webhookevent" not in CORE_BACKUP_TABLES
    assert set(CORE_FORBIDDEN_TABLES).isdisjoint(CORE_BACKUP_TABLES)


def test_keys_are_environment_scoped_and_deterministic():
    keys = keys_for_backup("production", "core", datetime(2026, 5, 3, 12, 0, tzinfo=UTC))

    assert keys.backup_key == "production/core/2026/05/03/core-20260503T120000Z.dump.zst.age"
    assert keys.manifest_key == ("production/core/2026/05/03/core-20260503T120000Z.manifest.json")
    assert keys.latest_key == "production/core/latest.json"


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_requires_postgresql_and_pgpassword_is_subprocess_only(monkeypatch, tmp_path):
    connection_info = get_postgres_connection_info()
    captured = {}

    def fake_run(command, check, env=None):
        captured["command"] = command
        captured["env"] = env

    monkeypatch.setattr("apps.common.backups.postgres.subprocess.run", fake_run)

    pg_dump(
        connection_info=connection_info,
        output_path=tmp_path / "backup.dump",
        tables=("accounts_user",),
        data_only=True,
    )

    assert "super-secret-db-password" not in captured["command"]
    assert captured["env"]["PGPASSWORD"] == "super-secret-db-password"
    assert "--data-only" in captured["command"]
    assert captured["command"].count("--table") == 1


def test_rejects_non_postgresql_database(settings):
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

    with pytest.raises(Exception, match="PostgreSQL"):
        get_postgres_connection_info()


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_backup_dry_run_prints_tables_without_dump_or_upload(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("dry run should not perform backup side effects")

    monkeypatch.setattr("apps.common.management.commands.backup_database.pg_dump", fail)
    monkeypatch.setattr("apps.common.management.commands.backup_database.R2Storage", fail)

    call_command("backup_database", "--mode", "core", "--dry-run")


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_restore_dry_run_verifies_checksum_before_decrypt(monkeypatch, tmp_path):
    encrypted = tmp_path / "core.dump.zst.age"
    encrypted.write_bytes(b"encrypted-backup")
    manifest = build_test_manifest("core", encrypted)
    keys = keys_for_backup("production", "core", datetime(2026, 5, 3, 12, 0, tzinfo=UTC))
    pointer = {"manifest_key": keys.manifest_key}

    class PointerStorage:
        def __init__(self, settings):
            pass

        def get_bytes(self, key):
            if key.endswith("latest.json"):
                return json.dumps(pointer).encode()
            return json.dumps(manifest).encode()

        def download_file(self, *, key, path):
            Path(path).write_bytes(encrypted.read_bytes())

    def fail_decrypt(*args, **kwargs):
        raise AssertionError("dry run must not decrypt")

    configure_fake_r2_env(monkeypatch)
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.R2Storage", PointerStorage
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.age_decrypt", fail_decrypt
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.validate_migration_compatibility",
        lambda manifest, mode=None: None,
    )

    call_command(
        "restore_database",
        "--mode",
        "core",
        "--backup-key",
        "production/core/latest.json",
        "--dry-run",
    )


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_full_restore_without_require_empty_db_refuses_to_run():
    with pytest.raises(CommandError, match="Full restore requires --require-empty-db"):
        call_command(
            "restore_database", "--mode", "full", "--backup-key", "production/full/latest.json"
        )


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_full_restore_with_non_empty_db_refuses_to_run(monkeypatch, tmp_path):
    encrypted = tmp_path / "full.dump.zst.age"
    encrypted.write_bytes(b"encrypted-full-backup")
    FakeStorage.manifest = build_test_manifest("full", encrypted)
    FakeStorage.encrypted_payload = encrypted.read_bytes()

    configure_fake_r2_env(monkeypatch)
    monkeypatch.setattr("apps.common.management.commands.restore_database.R2Storage", FakeStorage)
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.validate_migration_compatibility",
        lambda manifest, mode=None: None,
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.check_database_empty_for_full_restore",
        lambda: FullRestoreEmptinessCheck(non_empty_tables=("accounts_user",)),
    )

    with pytest.raises(CommandError, match="fresh migrated database"):
        call_command(
            "restore_database",
            "--mode",
            "full",
            "--backup-key",
            "production/full/2026/05/03/full-20260503T120000Z.manifest.json",
            "--require-empty-db",
        )


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_full_restore_dry_run_validates_checksum_without_db_writes(monkeypatch, tmp_path):
    encrypted = tmp_path / "full.dump.zst.age"
    encrypted.write_bytes(b"encrypted-full-backup")
    FakeStorage.manifest = build_test_manifest("full", encrypted)
    FakeStorage.encrypted_payload = encrypted.read_bytes()

    configure_fake_r2_env(monkeypatch)
    monkeypatch.setattr("apps.common.management.commands.restore_database.R2Storage", FakeStorage)
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.validate_migration_compatibility",
        lambda manifest, mode=None: None,
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.check_database_empty_for_full_restore",
        lambda: (_ for _ in ()).throw(AssertionError("dry run must not check DB emptiness")),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.age_decrypt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry run must not decrypt")),
    )

    call_command(
        "restore_database",
        "--mode",
        "full",
        "--backup-key",
        "production/full/2026/05/03/full-20260503T120000Z.manifest.json",
        "--dry-run",
    )


@override_settings(DATABASES=POSTGRES_DATABASES)
def test_core_restore_reseeds_sequences_after_data_only_restore(monkeypatch, tmp_path):
    encrypted = tmp_path / "core.dump.zst.age"
    encrypted.write_bytes(b"encrypted-core-backup")
    FakeStorage.manifest = build_test_manifest("core", encrypted)
    FakeStorage.encrypted_payload = encrypted.read_bytes()
    calls = []

    configure_fake_r2_env(monkeypatch)
    monkeypatch.setenv("BACKUP_AGE_PRIVATE_KEY", "AGE-SECRET-KEY-test")
    monkeypatch.setattr("apps.common.management.commands.restore_database.R2Storage", FakeStorage)
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.validate_migration_compatibility",
        lambda manifest, mode=None: None,
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.check_no_business_data",
        lambda: type("BusinessCheck", (), {"has_business_data": False})(),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.truncate_core_tables",
        lambda: calls.append("truncate"),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.age_decrypt",
        lambda *args, **kwargs: calls.append("decrypt"),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.zstd_decompress",
        lambda *args, **kwargs: calls.append("decompress"),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.pg_restore",
        lambda *args, **kwargs: calls.append("pg_restore"),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.reseed_core_sequences",
        lambda: calls.append("reseed"),
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.expire_pending_invitations_after_restore",
        lambda: calls.append("expire") or 0,
    )
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.call_command",
        lambda *a, **k: calls.append("check"),
    )

    call_command(
        "restore_database",
        "--mode",
        "core",
        "--backup-key",
        "production/core/2026/05/03/core-20260503T120000Z.manifest.json",
        "--require-empty-db",
    )

    assert calls == ["decrypt", "decompress", "truncate", "pg_restore", "reseed", "expire", "check"]


def test_reseed_table_sequences_sets_sequence_from_restored_values(monkeypatch):
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return ["public.accounts_user_id_seq"]

    class FakeConnection:
        ops = type("Ops", (), {"quote_name": staticmethod(lambda value: f'"{value}"')})()

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("apps.common.backups.restore.connection", FakeConnection())
    monkeypatch.setattr(
        "apps.common.backups.restore.sequence_columns_for_table", lambda table: ("id",)
    )

    reseed_table_sequences(("accounts_user",))

    assert executed[0] == ("SELECT pg_get_serial_sequence(%s, %s)", ["public.accounts_user", "id"])
    assert "setval" in executed[1][0]
    assert 'COALESCE(MAX("id"), 1)' in executed[1][0]
    assert 'MAX("id") IS NOT NULL' in executed[1][0]
    assert executed[1][1] == ["public.accounts_user_id_seq"]


def test_object_matches_requires_size_and_sha_metadata():
    storage = R2Storage.__new__(R2Storage)

    storage.head = lambda key: {"ContentLength": 12, "Metadata": {"sha256": "abc"}}
    assert storage.object_matches(key="backup", size_bytes=12, sha256="abc")

    storage.head = lambda key: {"ContentLength": 12, "Metadata": {}}
    assert not storage.object_matches(key="backup", size_bytes=12, sha256="abc")

    storage.head = lambda key: {"ContentLength": 12, "Metadata": {"sha256": "wrong"}}
    assert not storage.object_matches(key="backup", size_bytes=12, sha256="abc")

    storage.head = lambda key: {"ContentLength": 99, "Metadata": {"sha256": "abc"}}
    assert not storage.object_matches(key="backup", size_bytes=12, sha256="abc")


def test_core_migration_compatibility_ignores_unrelated_app_mismatch(monkeypatch):
    manifest = {
        "backup_type": "core",
        "migration_heads": {"accounts": "0001_initial", "trainerlab": "9999_future"},
    }
    monkeypatch.setattr(
        "apps.common.backups.manifest.get_migration_heads",
        lambda: {"accounts": "0001_initial", "trainerlab": "0001_initial"},
    )

    validate_migration_compatibility(manifest, mode="core")


def test_core_migration_compatibility_fails_on_relevant_app_mismatch(monkeypatch):
    manifest = {"backup_type": "core", "migration_heads": {"accounts": "0002_changed"}}
    monkeypatch.setattr(
        "apps.common.backups.manifest.get_migration_heads", lambda: {"accounts": "0001_initial"}
    )

    with pytest.raises(ValueError, match="accounts"):
        validate_migration_compatibility(manifest, mode="core")


def test_full_migration_compatibility_fails_on_any_mismatch(monkeypatch):
    manifest = {"backup_type": "full", "migration_heads": {"trainerlab": "9999_future"}}
    monkeypatch.setattr(
        "apps.common.backups.manifest.get_migration_heads",
        lambda: {"trainerlab": "0001_initial"},
    )

    with pytest.raises(ValueError, match="trainerlab"):
        validate_migration_compatibility(manifest, mode="full")


@pytest.mark.django_db
def test_business_data_check_allows_seed_users_but_flags_real_users():
    role = UserRole.objects.create(title="Clinician")
    assert not check_no_business_data().has_business_data

    User.objects.create(email="real@example.com", role=role)

    result = check_no_business_data()
    assert result.has_business_data
    assert result.non_seed_user_count == 1


@pytest.mark.django_db
def test_pending_invitations_expire_after_restore_transaction():
    role = UserRole.objects.create(title="Clinician")
    owner = User.objects.create(email="owner@example.com", role=role)
    account = Account.objects.get(owner_user=owner, account_type=Account.AccountType.PERSONAL)
    invitation = Invitation.objects.create(
        email="invitee@example.com",
        invited_by=owner,
        claimed_account=account,
        expires_at=timezone.now() + timedelta(days=3),
    )

    expired_count = expire_pending_invitations_after_restore()

    invitation.refresh_from_db()
    assert expired_count == 1
    assert invitation.expires_at <= timezone.now()


def test_core_truncate_order_is_deterministic_and_fk_safe_shape():
    truncate_order = tuple(reversed(CORE_BACKUP_TABLES))
    assert truncate_order[0] == "billing_seatassignment"
    assert truncate_order[-1] == "django_content_type"


def test_advisory_lock_refuses_overlap(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            self.sql = sql
            self.params = params

        def fetchone(self):
            return [False]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("apps.common.backups.postgres.connection", FakeConnection())

    with (
        pytest.raises(CommandError, match="Another backup is already running"),
        backup_advisory_lock(),
    ):
        pass

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

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
    CORE_TRUNCATE_TABLES,
)
from apps.common.backups.manifest import build_manifest, keys_for_backup, sha256_file
from apps.common.backups.postgres import backup_advisory_lock, pg_dump
from apps.common.backups.restore import (
    check_no_business_data,
    expire_pending_invitations_after_restore,
)

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


def test_core_allowlist_excludes_runtime_and_audit_tables():
    assert "django_session" not in CORE_BACKUP_TABLES
    assert "accounts_accountauditevent" not in CORE_BACKUP_TABLES
    assert "accounts_invitationauditevent" not in CORE_BACKUP_TABLES
    assert "billing_webhookevent" not in CORE_BACKUP_TABLES
    assert set(CORE_FORBIDDEN_TABLES).isdisjoint(CORE_BACKUP_TABLES)


def test_keys_are_environment_scoped_and_deterministic():
    keys = keys_for_backup("production", "core", datetime(2026, 5, 3, 12, 0, tzinfo=UTC))

    assert keys.backup_key == "production/core/2026/05/03/core-20260503T120000Z.dump.zst.age"
    assert keys.manifest_key == (
        "production/core/2026/05/03/core-20260503T120000Z.manifest.json"
    )
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
    checksum = sha256_file(encrypted)
    keys = keys_for_backup("production", "core", datetime(2026, 5, 3, 12, 0, tzinfo=UTC))
    manifest = build_manifest(
        mode="core",
        environment="production",
        database_name="medsim",
        tables=CORE_BACKUP_TABLES,
        keys=keys,
        sha256=checksum,
        size_bytes=encrypted.stat().st_size,
        created_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        migration_heads={"accounts": "0001_initial"},
    )
    pointer = {"manifest_key": keys.manifest_key}

    class FakeStorage:
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

    monkeypatch.setenv("BACKUP_R2_BUCKET", "bucket")
    monkeypatch.setenv("BACKUP_R2_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("BACKUP_R2_ACCESS_KEY_ID", "read-key")
    monkeypatch.setenv("BACKUP_R2_SECRET_ACCESS_KEY", "read-secret")
    monkeypatch.setattr("apps.common.management.commands.restore_database.R2Storage", FakeStorage)
    monkeypatch.setattr("apps.common.management.commands.restore_database.age_decrypt", fail_decrypt)
    monkeypatch.setattr(
        "apps.common.management.commands.restore_database.validate_migration_compatibility",
        lambda manifest: None,
    )

    call_command(
        "restore_database",
        "--mode",
        "core",
        "--backup-key",
        "production/core/latest.json",
        "--dry-run",
    )


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
    assert tuple(reversed(CORE_BACKUP_TABLES)) == CORE_TRUNCATE_TABLES
    assert CORE_TRUNCATE_TABLES[0] == "billing_seatassignment"
    assert CORE_TRUNCATE_TABLES[-1] == "django_content_type"


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

    with pytest.raises(CommandError, match="Another backup is already running"), backup_advisory_lock():
        pass

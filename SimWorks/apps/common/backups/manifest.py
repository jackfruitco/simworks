"""Manifest and object key helpers for encrypted backup artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader

MANIFEST_VERSION = 1


@dataclass(frozen=True)
class BackupKeys:
    backup_key: str
    manifest_key: str
    latest_key: str


def timestamp_slug(created_at: datetime) -> str:
    return created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def keys_for_backup(environment: str, mode: str, created_at: datetime) -> BackupKeys:
    day_path = created_at.astimezone(UTC).strftime("%Y/%m/%d")
    stamp = timestamp_slug(created_at)
    prefix = f"{environment}/{mode}/{day_path}"
    basename = f"{mode}-{stamp}"
    return BackupKeys(
        backup_key=f"{prefix}/{basename}.dump.zst.age",
        manifest_key=f"{prefix}/{basename}.manifest.json",
        latest_key=f"{environment}/{mode}/latest.json",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def get_migration_heads() -> dict[str, str]:
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    heads: dict[str, str] = {}
    for app_label, migration_name in loader.graph.leaf_nodes():
        heads[app_label] = migration_name
    return dict(sorted(heads.items()))


def build_manifest(
    *,
    mode: str,
    environment: str,
    database_name: str,
    tables: tuple[str, ...],
    keys: BackupKeys,
    sha256: str,
    size_bytes: int,
    created_at: datetime | None = None,
    migration_heads: dict[str, str] | None = None,
) -> dict[str, Any]:
    created = created_at or datetime.now(UTC)
    return {
        "manifest_version": MANIFEST_VERSION,
        "created_at": created.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "backup_type": mode,
        "environment": environment,
        "app_version": getattr(settings, "APP_VERSION", "0.11.0"),
        "git_sha": get_git_sha(),
        "django_settings_module": getattr(settings, "SETTINGS_MODULE", ""),
        "database_name": database_name,
        "tables": list(tables),
        "migration_heads": migration_heads if migration_heads is not None else get_migration_heads(),
        "compression": "zstd",
        "encryption": "age",
        "sha256": sha256,
        "size_bytes": size_bytes,
        "backup_key": keys.backup_key,
        "manifest_key": keys.manifest_key,
    }


def manifest_json(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def parse_manifest(raw: bytes | str) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    manifest = json.loads(raw)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any], *, expected_mode: str | None = None) -> None:
    required_fields = {
        "manifest_version",
        "created_at",
        "backup_type",
        "environment",
        "database_name",
        "tables",
        "migration_heads",
        "compression",
        "encryption",
        "sha256",
        "size_bytes",
        "backup_key",
        "manifest_key",
    }
    missing = sorted(required_fields.difference(manifest))
    if missing:
        raise ValueError(f"Backup manifest missing required fields: {', '.join(missing)}")
    if manifest["manifest_version"] != MANIFEST_VERSION:
        raise ValueError("Unsupported backup manifest version.")
    if expected_mode and manifest["backup_type"] != expected_mode:
        raise ValueError(
            f"Backup mode mismatch: expected {expected_mode}, got {manifest['backup_type']}."
        )
    if manifest["compression"] != "zstd":
        raise ValueError("Unsupported backup compression.")
    if manifest["encryption"] != "age":
        raise ValueError("Unsupported backup encryption.")
    if not isinstance(manifest["tables"], list):
        raise ValueError("Backup manifest tables must be a list.")


def validate_migration_compatibility(manifest: dict[str, Any]) -> None:
    current_heads = get_migration_heads()
    backup_heads = manifest.get("migration_heads") or {}
    mismatches = []
    for app_label, backup_head in backup_heads.items():
        current_head = current_heads.get(app_label)
        if current_head != backup_head:
            mismatches.append(f"{app_label}: backup={backup_head}, current={current_head}")
    if mismatches:
        raise ValueError("Backup migration heads do not match current schema: " + "; ".join(mismatches))

"""Preflight checks for PostgreSQL logical backups."""

from __future__ import annotations

import re
import subprocess

from django.core.management.base import CommandError
from django.db import connection

PG_DUMP_VERSION_RE = re.compile(r"pg_dump\s+\(PostgreSQL\)\s+(\d+)(?:\.|\b)")


def parse_pg_dump_major(version_output: str) -> int:
    match = PG_DUMP_VERSION_RE.search(version_output.strip())
    if not match:
        raise CommandError(
            f"Could not parse pg_dump major version from output: {version_output!r}"
        )
    return int(match.group(1))


def parse_server_major(server_version_num: object) -> int:
    raw_value = str(server_version_num).strip()
    if not raw_value.isdigit():
        raise CommandError(
            f"Could not parse PostgreSQL server_version_num value: {server_version_num!r}"
        )

    version_num = int(raw_value)
    if version_num <= 0:
        raise CommandError(
            f"Could not parse PostgreSQL server_version_num value: {server_version_num!r}"
        )
    return version_num // 10000


def get_pg_dump_major() -> int:
    try:
        result = subprocess.run(
            ["pg_dump", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CommandError("Required backup tool is not installed: pg_dump") from exc
    except subprocess.CalledProcessError as exc:
        raise CommandError("Could not run pg_dump --version for backup preflight.") from exc

    return parse_pg_dump_major(result.stdout)


def get_server_major() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num;")
        row = cursor.fetchone()

    if not row:
        raise CommandError("Could not read PostgreSQL server_version_num for backup preflight.")
    return parse_server_major(row[0])


def validate_pg_dump_server_compatibility() -> None:
    pg_dump_major = get_pg_dump_major()
    server_major = get_server_major()

    if pg_dump_major < server_major:
        raise CommandError(
            "PostgreSQL backup client/server mismatch: "
            f"server major version is {server_major}, "
            f"but pg_dump major version is {pg_dump_major}. "
            f"Install postgresql-client-{server_major} in the backup runner image "
            f"or set POSTGRES_CLIENT_MAJOR={server_major}."
        )

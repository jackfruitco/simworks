"""PostgreSQL tool wrappers for logical backup and restore."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shlex
import subprocess

from django.core.management.base import CommandError
from django.db import connection

from .config import PostgresConnectionInfo
from .inventory import BACKUP_ADVISORY_LOCK_ID


def run_checked(command: list[str], *, env: dict[str, str] | None = None) -> None:
    try:
        subprocess.run(command, check=True, env=env)
    except FileNotFoundError as exc:
        raise CommandError(f"Required backup tool is not installed: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        rendered = " ".join(shlex.quote(part) for part in command)
        raise CommandError(f"Backup tool failed: {rendered}") from exc


def pg_dump(
    *,
    connection_info: PostgresConnectionInfo,
    output_path: Path,
    tables: tuple[str, ...] = (),
    data_only: bool = False,
) -> None:
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file",
        str(output_path),
        *connection_info.command_args(),
    ]
    if data_only:
        command.append("--data-only")
    for table in tables:
        command.extend(["--table", table])
    run_checked(command, env=connection_info.subprocess_env())


def pg_restore(
    *,
    connection_info: PostgresConnectionInfo,
    input_path: Path,
) -> None:
    command = [
        "pg_restore",
        "--single-transaction",
        "--no-owner",
        "--no-acl",
        "--dbname",
        connection_info.dbname,
    ]
    if connection_info.host:
        command.extend(["--host", connection_info.host])
    if connection_info.port:
        command.extend(["--port", str(connection_info.port)])
    if connection_info.user:
        command.extend(["--username", connection_info.user])
    command.append(str(input_path))
    run_checked(command, env=connection_info.subprocess_env())


def zstd_compress(input_path: Path, output_path: Path) -> None:
    run_checked(["zstd", "--force", str(input_path), "-o", str(output_path)])


def zstd_decompress(input_path: Path, output_path: Path) -> None:
    run_checked(["zstd", "--decompress", "--force", str(input_path), "-o", str(output_path)])


def age_encrypt(input_path: Path, output_path: Path, public_key: str) -> None:
    run_checked(["age", "-r", public_key, "-o", str(output_path), str(input_path)])


def age_decrypt(input_path: Path, output_path: Path, private_key: str) -> None:
    identity_path = output_path.with_suffix(output_path.suffix + ".identity")
    try:
        identity_path.write_text(private_key + "\n", encoding="utf-8")
        identity_path.chmod(0o600)
        run_checked(["age", "-d", "-i", str(identity_path), "-o", str(output_path), str(input_path)])
    finally:
        identity_path.unlink(missing_ok=True)


@contextmanager
def backup_advisory_lock() -> Iterator[None]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [BACKUP_ADVISORY_LOCK_ID])
        locked = cursor.fetchone()[0]
        if not locked:
            raise CommandError("Another backup is already running; advisory lock is held.")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [BACKUP_ADVISORY_LOCK_ID])

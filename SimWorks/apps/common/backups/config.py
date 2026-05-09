"""Configuration helpers for PostgreSQL backup commands."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

POSTGRES_BACKENDS = {
    "django.db.backends.postgresql",
    "django.db.backends.postgresql_psycopg2",
}


@dataclass(frozen=True)
class PostgresConnectionInfo:
    dbname: str
    user: str
    password: str
    host: str
    port: str

    def command_args(self) -> list[str]:
        args = ["--dbname", self.dbname]
        if self.host:
            args.extend(["--host", self.host])
        if self.port:
            args.extend(["--port", str(self.port)])
        if self.user:
            args.extend(["--username", self.user])
        return args

    def subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.password:
            env["PGPASSWORD"] = self.password
        return env


@dataclass(frozen=True)
class R2Settings:
    bucket: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str


def get_postgres_connection_info(alias: str = "default") -> PostgresConnectionInfo:
    database: dict[str, Any] = settings.DATABASES[alias]
    engine = database.get("ENGINE")
    if engine not in POSTGRES_BACKENDS:
        raise ImproperlyConfigured("Database backups require PostgreSQL as the default database.")

    return PostgresConnectionInfo(
        dbname=str(database.get("NAME") or ""),
        user=str(database.get("USER") or ""),
        password=str(database.get("PASSWORD") or ""),
        host=str(database.get("HOST") or ""),
        port=str(database.get("PORT") or ""),
    )


def get_backup_environment() -> str:
    return os.environ.get("BACKUP_ENVIRONMENT", "local").strip() or "local"


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def get_r2_settings() -> R2Settings:
    return R2Settings(
        bucket=get_required_env("BACKUP_R2_BUCKET"),
        endpoint_url=get_required_env("BACKUP_R2_ENDPOINT_URL"),
        access_key_id=get_required_env("BACKUP_R2_ACCESS_KEY_ID"),
        secret_access_key=get_required_env("BACKUP_R2_SECRET_ACCESS_KEY"),
    )

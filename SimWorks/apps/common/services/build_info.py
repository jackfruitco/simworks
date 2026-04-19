"""Build metadata helpers for frontend splash/startup and debug display."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import tomllib
from typing import Any

ORCHESTRAI_PACKAGE_NAME = "orchestrai"
BACKEND_COMMIT_ENV_VARS = ("APP_GIT_SHA", "GIT_SHA")
BACKEND_BUILD_TIME_ENV_VARS = ("APP_BUILD_TIME", "BUILD_TIME")
PYPROJECT_TOML_PATH = Path(__file__).resolve().parents[4] / "pyproject.toml"


def safe_package_version(package_name: str) -> str | None:
    """Return installed package version metadata when available."""
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def get_backend_package_name() -> str | None:
    """Return the canonical backend distribution name from ``pyproject.toml``."""
    try:
        project_data = tomllib.loads(PYPROJECT_TOML_PATH.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None

    package_name = str(project_data.get("project", {}).get("name") or "").strip()
    return package_name or None


def get_backend_version() -> str | None:
    """Return the installed backend package version using the canonical project name."""
    package_name = get_backend_package_name()
    if not package_name:
        return None
    return safe_package_version(package_name)


def _first_non_blank_env_value(env_vars: tuple[str, ...]) -> str | None:
    """Return the first non-blank environment value from the provided precedence list."""
    for env_var in env_vars:
        value = os.getenv(env_var, "").strip()
        if value:
            return value
    return None


def get_backend_commit() -> str | None:
    """Return the injected backend commit SHA from the environment."""
    return _first_non_blank_env_value(BACKEND_COMMIT_ENV_VARS)


def get_backend_build_time() -> str | None:
    """Return the injected UTC artifact build timestamp from the environment."""
    return _first_non_blank_env_value(BACKEND_BUILD_TIME_ENV_VARS)


def get_orchestrai_version() -> str | None:
    """Return the installed OrchestrAI package version."""
    return safe_package_version(ORCHESTRAI_PACKAGE_NAME)


def get_build_info_payload() -> dict[str, Any]:
    """Return best-effort build metadata for client startup/debug display."""
    return {
        "backend": {
            "version": get_backend_version(),
            "commit": get_backend_commit(),
            "build_time": get_backend_build_time(),
        },
        "orchestrai": {
            "version": get_orchestrai_version(),
        },
    }

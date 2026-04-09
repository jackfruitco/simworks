"""Build metadata helpers for frontend splash/startup display."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

BACKEND_PACKAGE_NAME = "MedSim"
ORCHESTRAI_PACKAGE_NAME = "orchestrai"
BACKEND_COMMIT_ENV_VARS = ("APP_GIT_SHA", "GIT_SHA")


def safe_package_version(package_name: str) -> str | None:
    """Return installed package version metadata when available."""
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def get_backend_version() -> str | None:
    """Return the installed MedSim package version."""
    return safe_package_version(BACKEND_PACKAGE_NAME)


def get_backend_commit() -> str | None:
    """Return the injected backend commit SHA from the environment."""
    for env_var in BACKEND_COMMIT_ENV_VARS:
        value = os.getenv(env_var, "").strip()
        if value:
            return value
    return None


def get_orchestrai_version() -> str | None:
    """Return the installed OrchestrAI package version."""
    return safe_package_version(ORCHESTRAI_PACKAGE_NAME)


def get_build_info_payload() -> dict[str, Any]:
    """Return best-effort build metadata for client splash screens."""
    return {
        "backend": {
            "version": get_backend_version(),
            "commit": get_backend_commit(),
            "build_time": None,
        },
        "orchestrai": {
            "version": get_orchestrai_version(),
        },
    }

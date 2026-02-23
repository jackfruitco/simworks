# orchestrai/utils/env.py
"""Environment variable utilities for OrchestrAI."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrai import OrchestrAI


def get_api_key_envvar(provider: str, app: "OrchestrAI | None" = None) -> str | None:
    """
    Get the configured environment variable name for a provider's API key.

    Reads from ``app.conf["API_KEY_ENVVARS"][provider]``.

    Args:
        provider: Provider name (e.g., "openai", "anthropic")
        app: OrchestrAI app instance. If None, uses get_current_app().

    Returns:
        Environment variable name (e.g., "OPENAI_API_KEY") or None if not configured
    """
    if app is None:
        from orchestrai import get_current_app

        app = get_current_app()

    if not app or not app.conf:
        return None

    envvars = app.conf.get("API_KEY_ENVVARS", {})
    return envvars.get(provider)


def get_api_key(provider: str, app: "OrchestrAI | None" = None) -> str | None:
    """
    Get the API key for a provider using the configured environment variable.

    Lookup:
    1. Get env var name from ``app.conf["API_KEY_ENVVARS"][provider]``
    2. Read that env var from ``os.environ``

    Args:
        provider: Provider name (e.g., "openai", "anthropic")
        app: OrchestrAI app instance. If None, uses get_current_app().

    Returns:
        API key string or None if not found

    Example:
        >>> # With OPENAI_API_KEY="sk-..." in environment
        >>> get_api_key("openai")
        'sk-...'
    """
    envvar_name = get_api_key_envvar(provider, app)

    if not envvar_name:
        return None

    return os.environ.get(envvar_name)

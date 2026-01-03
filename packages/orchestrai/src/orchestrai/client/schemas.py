# orchestrai/client/schemas.py

"""
Strict configuration schemas for backend-agnostic AI client orchestration.

These models are hydrated from validated provider and client settings (`OrcaClientsSettings`).

- OrcaClientRegistration: runtime registration object created from validated provider + client settings.
- OrcaClientConfig:       resolved runtime behavior config (timeouts, retries, telemetry, etc.) derived from
                          global defaults plus per-client overrides.

Design notes:
- We forbid unknown keys (extra="forbid") to catch typos at startup.
- Backend wiring (base URL, model, API key, etc.) is handled by the provider layer and not represented here.
"""

from typing import Any, Dict, Optional, cast

from pydantic import BaseModel

from orchestrai.conf import DEFAULTS


CLIENT_DEFAULT_TIMEOUT = cast(float | None, DEFAULTS["CLIENT_DEFAULT_TIMEOUT"])
CLIENT_DEFAULT_MAX_RETRIES = cast(int, DEFAULTS["CLIENT_DEFAULT_MAX_RETRIES"])
CLIENT_DEFAULT_TELEMETRY_ENABLED = cast(bool, DEFAULTS["CLIENT_DEFAULT_TELEMETRY_ENABLED"])
CLIENT_DEFAULT_LOG_PROMPTS = cast(bool, DEFAULTS["CLIENT_DEFAULT_LOG_PROMPTS"])
CLIENT_DEFAULT_RAISE_ON_ERROR = cast(bool, DEFAULTS["CLIENT_DEFAULT_RAISE_ON_ERROR"])
from pydantic.config import ConfigDict

__all__ = [
    "OrcaClientRegistration",
    "OrcaClientConfig",
    "semantic_provider_name",
]


def semantic_provider_name(provider_key: str, label: str | None) -> str:
    """
    Return a human-friendly semantic name for observability and logs.

    Examples:
        semantic_provider_name("openai", None)      -> "openai"
        semantic_provider_name("openai", "prod")    -> "openai:prod"
        semantic_provider_name("anthropic", "lab1") -> "anthropic:lab1"

    Note: The first argument is a provider alias, and the second is typically an api_key_alias or other label, not a raw provider key.
    """
    key = (provider_key or "").strip()
    lab = (label or "").strip()
    if lab:
        return f"{key}:{lab}"
    return key


class OrcaClientRegistration(BaseModel):
    """
    Strict runtime registration object used by the Orca registry.

    This object is derived from `OrcaClientsSettings` and `ProvidersSettings` after normalization,
    not directly from raw Django settings.

    Fields:
        alias:           The Orca client alias (index into CLIENTS).
        provider_alias:  The provider alias (index into PROVIDERS).
        profile_alias:   The provider profile alias (index into PROVIDERS[provider_alias].profiles).
        api_key_alias:   The alias into PROVIDERS[provider_alias].api_key_envvar if that is a dict.
        config:          The fully-resolved runtime behavior config for this client.
        default:         Whether this registration represents the default client (should mirror DEFAULT_CLIENT == alias).
        enabled:         Whether this registration should be active in the registry.
        healthcheck:     Whether to include this client in healthchecks.

    Notes:
        - Backend wiring (base URL, model, API key, etc.) is handled by the provider layer and not represented here.
        - Extra keys are forbidden.
    """
    alias: str
    provider_alias: str
    profile_alias: str
    api_key_alias: Optional[str] = None

    config: OrcaClientConfig

    default: bool = False
    enabled: bool = True
    healthcheck: bool = True

    model_config = ConfigDict(extra="forbid")


class OrcaClientConfig(BaseModel):
    """
    Runtime configuration for `OrcaClient` behavior (STRICT).

    This is derived from `OrcaClientDefaults` plus per-client overrides.

    This configuration strictly controls client-level behavior such as timeouts, retries, telemetry,
    and logging; it does not include provider-side tuning like model or temperature.

    Fields (sane defaults):
        max_retries:        Max number of retries on transient errors.
        timeout_s:          Optional per-call timeout (seconds). If None, backend default is used.
        telemetry_enabled:  Whether to emit client-level telemetry (spans/metrics).
        log_prompts:        Whether to log prompts for debugging (be careful in prod).
        raise_on_error:     If True, client raises ProviderError-like exceptions; if False, returns error-y results.

    Notes:
        - Extra keys are forbidden to catch typos early.
        - Extend cautiously and mirror in system checks / OrcaClientsSettings.
    """
    max_retries: int = CLIENT_DEFAULT_MAX_RETRIES
    timeout_s: Optional[float] = CLIENT_DEFAULT_TIMEOUT
    telemetry_enabled: bool = CLIENT_DEFAULT_TELEMETRY_ENABLED
    log_prompts: bool = CLIENT_DEFAULT_LOG_PROMPTS
    raise_on_error: bool = CLIENT_DEFAULT_RAISE_ON_ERROR

    model_config = ConfigDict(extra="forbid")

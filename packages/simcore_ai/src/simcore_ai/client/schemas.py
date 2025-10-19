# simcore_ai/client/schemas.py
from __future__ import annotations

"""
Strict configuration schemas for provider wiring and client orchestration.

This module intentionally lives under `simcore_ai.client` to avoid import
cycles and to keep concerns clear:

- AIProviderConfig:      provider *wiring* only (vendor slug, base_url, auth, default model, etc.)
- AIClientRegistration:  app-level *orchestration* (client name, default/enabled) + a small
                         WHITELIST of provider-field overrides (model, base_url, api_key, api_key_env, timeout_s)
                         and optional runtime knobs via `client_config`.
- AIClientConfig:        runtime client *behavior* (retries, timeout, telemetry, logging). Built from
                         `SIMCORE_AI["CLIENT_DEFAULTS"]` and passed to `AIClient(...)` at registration time.

Design notes:
- We forbid unknown keys (extra="forbid") to catch typos at startup.
- Secrets resolution (api_key precedence) happens in the factory, not here.
- The semantic provider identity used for logging/telemetry is derived by
  `semantic_provider_name(provider_key, label)` -> "openai:prod".
"""

from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel
from pydantic.config import ConfigDict


__all__ = [
    "AIProviderConfig",
    "AIClientRegistration",
    "AIClientConfig",
    "semantic_provider_name",
]


def semantic_provider_name(provider_key: str, label: str | None) -> str:
    """
    Return a human-friendly semantic name for observability and logs.

    Examples:
        semantic_provider_name("openai", None)      -> "openai"
        semantic_provider_name("openai", "prod")    -> "openai:prod"
        semantic_provider_name("anthropic", "lab1") -> "anthropic:lab1"
    """
    key = (provider_key or "").strip()
    lab = (label or "").strip()
    if lab:
        return f"{key}:{lab}"
    return key


class AIProviderConfig(BaseModel):
    """
    Provider wiring (STRICT).

    Fields:
        provider:     Vendor slug (e.g., "openai", "anthropic", "vertex", "azure_openai", "local").
        label:        Optional disambiguator for multiple accounts/environments (e.g., "prod", "staging").
        base_url:     Optional custom endpoint.
        api_key:      Direct secret value (already resolved). Prefer env usage in production.
        api_key_env:  Name of environment variable to read the key from (resolved later in the factory).
        model:        Provider's default model for this wiring (clients may override).
        organization: Optional vendor-specific org/account identifier.
        timeout_s:    Default request timeout (seconds). Clients may override.

    Notes:
        - Extra keys are forbidden to catch mistakes early.
        - Secrets precedence is applied OUTSIDE this model (in the provider factory):
            client override -> provider value -> os.environ[api_key_env] (if set) -> None
    """
    provider: Literal["openai", "anthropic", "vertex", "azure_openai", "local"]
    label: Optional[str] = None

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None

    model: Optional[str] = None
    organization: Optional[str] = None
    timeout_s: Optional[float] = None

    model_config = ConfigDict(extra="forbid")


class AIClientRegistration(BaseModel):
    """
    Client registration (STRICT).

    This object is created from Django settings under SIMCORE_AI["CLIENTS"][<name>].

    Fields:
        name:         Registry key for the client (explicit, descriptive; e.g., "openai:prod-gpt-4o-mini-default").
        provider:     Key into SIMCORE_AI["PROVIDERS"] that supplies base wiring.
        default:      Whether this client should be treated as the default (policy: first True wins, others warn).
        enabled:      If False, this client is skipped during registration.

        # Whitelisted provider overrides (optional):
        model:        Override provider.model.
        base_url:     Override provider.base_url.
        api_key:      Override provider.api_key.
        api_key_env:  Override provider.api_key_env.
        timeout_s:    Override provider.timeout_s.

        # Runtime knobs (NOT part of provider wiring):
        client_config: Free-form dict passed to AIClient for runtime behavior (e.g., temperature, tracing).

    Notes:
        - Extra keys are forbidden.
        - This object does not resolve secrets; the factory will compute effective values.
    """
    name: str
    provider: str

    default: bool = False
    enabled: bool = True
    healthcheck: bool = True

    # Provider-field overrides (whitelist)
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout_s: Optional[float] = None

    # Runtime client knobs
    client_config: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="forbid")


class AIClientConfig(BaseModel):
    """
    Runtime configuration for `AIClient` behavior (STRICT).

    This is hydrated from `SIMCORE_AI["CLIENT_DEFAULTS"]` and supplied to
    `registry.create_client(..., client_config=AIClientConfig(...))`.

    Fields (sane defaults):
        max_retries:        Max number of retries on transient errors.
        timeout_s:          Optional per-call timeout (seconds). If None, provider default is used.
        telemetry_enabled:  Whether to emit client-level telemetry (spans/metrics).
        log_prompts:        Whether to log prompts for debugging (be careful in prod).
        raise_on_error:     If True, client raises ProviderError-like exceptions; if False, returns error-y results.

    Notes:
        - Extra keys are forbidden to catch typos early.
        - Extend cautiously and mirror in system checks (SIMCORE_AI['CLIENT_DEFAULTS']).
    """
    max_retries: int = 3
    timeout_s: Optional[float] = None
    telemetry_enabled: bool = True
    log_prompts: bool = False
    raise_on_error: bool = True

    model_config = ConfigDict(extra="forbid")
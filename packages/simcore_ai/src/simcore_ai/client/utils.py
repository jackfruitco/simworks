# simcore_ai/client/utils.py
"""
simcore_ai.client.utils
=======================

Utility helpers for merging and resolving AI provider configurations
in the simcore_ai framework.

This module primarily supports Django and non-Django setup routines
that need to unify two configuration sources:

1. **AIProviderConfig** — provider-level wiring from `SIMCORE_AI["PROVIDERS"]`
   (vendor slug, base_url, api_key_env, timeout, etc.)

2. **AIClientRegistration** — client-level orchestration from
   `SIMCORE_AI["CLIENTS"]` (explicit name, overrides, enable/disable, etc.)

The merging logic defined here ensures deterministic, safe precedence rules
for API key resolution and connection parameters before the factory constructs
provider instances.

Core Responsibilities:
----------------------
- Merge provider and client configuration with explicit override precedence.
- Resolve API keys from profile variables when required.
- Generate consistent provider identity names for observability.
"""


import logging
import os
from typing import Optional

from simcore_ai.client.types import AIClientRegistration, semantic_provider_name
from simcore_ai.components.providerkit.provider import AIProviderConfig

logger = logging.getLogger(__name__)


def effective_provider_config(
        provider: AIProviderConfig,
        client: Optional[AIClientRegistration] = None,
) -> AIProviderConfig:
    """
    Construct an *effective* provider configuration by merging a provider definition
    with an optional client registration.

    This function applies deterministic override and resolution logic so that
    downstream provider factories receive a fully resolved `AIProviderConfig`
    suitable for instantiation.

    Precedence Rules:
        1. Client may override: `model`, `base_url`, `api_key`, `api_key_env`, `timeout_s`.
        2. Provider values are used when the client leaves fields unset.
        3. API key resolution order:
            a. `client.api_key` (explicit value)
            b. `provider.api_key`
            c. `os.environ[client.api_key_env or provider.api_key_env]`

    Args:
        provider: The base provider configuration from SIMCORE_AI["PROVIDERS"].
        client:   The client registration from SIMCORE_AI["CLIENTS"] (optional).

    Returns:
        AIProviderConfig: A new instance containing merged and resolved fields.
    """
    if not isinstance(provider, AIProviderConfig):
        raise TypeError(f"expected AIProviderConfig, got {type(provider)}")

    # Copy base provider fields
    merged = provider.model_copy(deep=True)

    # Apply client overrides if present
    if client is not None:
        # Only apply overrides if the field is set (not None)
        for field in ("model", "base_url", "api_key", "api_key_env", "timeout_s"):
            val = getattr(client, field, None)
            if val is not None:
                setattr(merged, field, val)

    # Resolve API key with precedence
    key = (
            (client.api_key if client and client.api_key else None)
            or provider.api_key
            or _resolve_from_env(client, provider)
    )

    merged.api_key = key

    # If no label, derive one for clarity
    if not merged.label and client is not None:
        merged.label = client.name

    logger.debug(
        "Resolved provider config: %s (model=%s, timeout=%s)",
        semantic_provider_name(merged.provider, merged.label) or "<unspecified>",
        merged.model,
        merged.timeout_s,
    )

    # NOTE: do not set display/observability names on the config object; the provider
    # factory assigns provider.name / provider_key / provider_label on the instance.

    return merged


def _resolve_from_env(
        client: Optional[AIClientRegistration],
        provider: AIProviderConfig,
) -> Optional[str]:
    """
    Resolve an API key from profile variables following precedence.

    Checks, in order:
        1. `client.api_key_env`
        2. `provider.api_key_env`

    Returns:
        The resolved API key value, or None if neither profile variable
        is defined or contains a non-empty value.
    """
    for env_key in (
            getattr(client, "api_key_env", None),
            getattr(provider, "api_key_env", None),
    ):
        if env_key:
            val = os.getenv(env_key)
            if val:
                return val
    return None

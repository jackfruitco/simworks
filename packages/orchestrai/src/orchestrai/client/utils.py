# orchestrai/client/utils.py
from __future__ import annotations

import os

from orchestrai.components.providerkit.provider import ProviderConfig
from orchestrai.client.schemas import OrcaClientRegistration


def effective_provider_config(
    prov_cfg: ProviderConfig,
    reg: OrcaClientRegistration,
) -> ProviderConfig:
    """
    Compute the effective ProviderConfig for a given Orca client registration.

    Right now this is a thin wrapper that simply returns the ProviderConfig
    produced from settings resolution. It exists as an extension hook in case
    future versions want to:
      - inject per-client overrides,
      - decorate the alias,
      - or add tracing/telemetry metadata to ProviderConfig.

    The function is intentionally side-effect-free: it must not read global
    settings or registry state.
    """
    # For now, no additional transformation is performed.
    # If you later add per-client provider tweaks, do so here.
    return prov_cfg


def _resolve_from_env(
        client: Optional[OrcaClientRegistration],
        provider: ProviderConfig,
) -> Optional[str]:
    """
    Resolve an API key from profile variables following precedence.

    Checks, in order:
        1. `client.api_key_env`
        2. `backend.api_key_env`

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

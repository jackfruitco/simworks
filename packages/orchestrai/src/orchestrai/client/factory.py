# orchestrai/client/factory.py

import logging

from .conf_models import OrcaClientsSettings
from .registry import (
    create_client,
    list_clients,
)
from .resolve import (
    get_client_entry_or_default,
    resolve_provider_alias,
    resolve_profile_alias,
    resolve_api_key,
    resolve_client_behavior,
    resolve_client_flags,
)
from .schemas import OrcaClientConfig, OrcaClientRegistration
from .utils import effective_provider_config
from .settings_loader import OrcaSettings, load_orca_settings
from ..components.providerkit.conf_models import (
    ProvidersSettings,
    ProviderSettingsEntry,
)
from ..components.providerkit.provider import ProviderConfig

logger = logging.getLogger(__name__)


# This function builds client configuration from settings.
# The "default" client alias is autoconfigured if not explicitly declared.
# It assumes settings are already validated for single vs POD mode by the config layer.
def _build_client_from_settings(
        core: OrcaSettings,
        client_alias: str,
) -> tuple[ProviderConfig, OrcaClientRegistration, OrcaClientConfig]:
    """
    Build provider config, client registration, and client behavior config
    for a given Orca client alias.

    The 'default' client alias is always supported, even if not explicitly
    declared in CLIENTS; it is synthesized from OrcaClientsSettings.defaults
    and DEFAULT_* pointers.
    """
    providers_settings: ProvidersSettings = core.PROVIDERS
    clients_settings: OrcaClientsSettings = core.CLIENTS

    # Resolve the client entry (or None for the synthetic 'default' client)
    centry = get_client_entry_or_default(clients_settings, client_alias)

    # Resolve provider and profile aliases
    provider_alias = resolve_provider_alias(
        core, providers_settings, centry, client_alias
    )
    pentry: ProviderSettingsEntry = providers_settings.root[provider_alias]

    profile_alias = resolve_profile_alias(
        core,
        pentry,
        centry,
        provider_alias,
    )

    # Resolve API key alias + envvar
    api_key_alias, api_key_env = resolve_api_key(
        core,
        pentry,
        centry,
        provider_alias,
    )

    # Backend identity and profile config
    backend_identity = pentry.backend
    prof_cfg = pentry.profiles[profile_alias]

    # Provider wiring comes from profile + api key env var
    prov_cfg = ProviderConfig(
        alias=provider_alias,
        backend=backend_identity,
        api_key_env=api_key_env,
        model=prof_cfg.model,
    )

    # Resolve client behavior (timeouts/retries/logging/etc.)
    client_cfg = resolve_client_behavior(clients_settings, centry)

    # Resolve flags for default/enabled/healthcheck
    is_default, enabled, healthcheck = resolve_client_flags(
        core,
        clients_settings,
        client_alias,
        centry,
    )

    reg = OrcaClientRegistration(
        alias=client_alias,
        provider_alias=provider_alias,
        profile_alias=profile_alias,
        api_key_alias=api_key_alias,
        config=client_cfg,
        default=is_default,
        enabled=enabled,
        healthcheck=healthcheck,
    )

    return prov_cfg, reg, client_cfg


def build_orca_client(
        core: OrcaSettings,
        client_alias: str,
        *,
        make_default: bool | None = None,
        replace: bool = True,
):
    """
    Build and register a single Orca client from OrcaSettings.

    This is the low-level factory that bootstrap should call in a loop.
    It does not perform any alias enumeration or mode detection.

    Args:
        core: Loaded OrcaSettings instance.
        client_alias: The client alias to build (e.g. "default").
        make_default: Optional override for whether this client should be
            registered as the default. If None, uses the value from the
            resolved OrcaClientRegistration.
        replace: Whether to replace an existing client with the same alias
            in the registry.

    Returns:
        The created OrcaClient instance.
    """
    prov_cfg, reg, client_cfg = _build_client_from_settings(core, client_alias)
    eff_prov_cfg = effective_provider_config(prov_cfg, reg)

    final_make_default = reg.default if make_default is None else make_default

    client = create_client(
        eff_prov_cfg,
        name=client_alias,
        make_default=final_make_default,
        replace=replace,
        client_config=client_cfg,
    )

    logger.info(
        "Configured Orca client '%s' "
        "(provider=%s, profile=%s, default=%s, enabled=%s, healthcheck=%s)",
        client_alias,
        reg.provider_alias,
        reg.profile_alias,
        reg.default,
        reg.enabled,
        reg.healthcheck,
    )

    return client


def get_client(name: str | None = None):
    """
    High-level factory for OrcaClient singletons.

    Resolution:
      1) If `name` is provided and a client by that alias already exists in the registry,
         return it.
      2) Otherwise, build a client from OrcaSettings (PROVIDERS/CLIENTS) and register it.
      3) If `name` is None, use OrcaSettings.DEFAULT_CLIENT.
    """
    core = load_orca_settings()

    client_alias = name or getattr(core, "DEFAULT_CLIENT", "default")

    existing = list_clients().get(client_alias)
    if existing is not None:
        return existing

    # Single-item build: let bootstrap or callers handle any looping.
    return build_orca_client(core, client_alias)


def get_orca_client(
        client: str | None = None,
        provider: str | None = None,
        profile: str | None = None,
):
    """
    High-level convenience API for obtaining an OrcaClient.

    Semantics:
      - If only `client` is provided (no provider/profile overrides), this
        delegates to `get_client(client)` and returns a registry-backed
        singleton OrcaClient.
      - If `provider` and/or `profile` are provided, an ad-hoc OrcaClient is
        constructed for this call only. It uses:
            * the specified provider/profile aliases when given,
            * the base client alias (or DEFAULT_CLIENT) for behavior defaults,
            * the provider wiring resolved from PROVIDERS/CLIENTS.
        This per-call client is NOT registered in the global client registry.
    """
    # Fast path: no overrides, just use the registry-backed client.
    if provider is None and profile is None:
        return get_client(client)

    core = load_orca_settings()
    client_alias = client or getattr(core, "DEFAULT_CLIENT", "default")

    providers_settings: ProvidersSettings = core.PROVIDERS
    clients_settings: OrcaClientsSettings = core.CLIENTS

    # Resolve the base client entry (or None for synthetic 'default')
    centry = get_client_entry_or_default(clients_settings, client_alias)

    providers_cfg = providers_settings.root

    # Resolve provider alias with optional override
    if provider is not None:
        if provider not in providers_cfg:
            raise ValueError(
                f"Unknown provider alias {provider!r} requested in get_orca_client(). "
                f"Available providers: {list(providers_cfg.keys())}"
            )
        provider_alias = provider
    else:
        provider_alias = resolve_provider_alias(
            core,
            providers_settings,
            centry,
            client_alias,
        )

    pentry: ProviderSettingsEntry = providers_cfg[provider_alias]

    # Resolve profile alias with optional override
    if profile is not None:
        profiles = pentry.profiles or {}
        if profile not in profiles:
            raise ValueError(
                f"Provider {provider_alias!r} has no profile {profile!r}. "
                f"Available profiles: {list(profiles.keys())}"
            )
        profile_alias = profile
    else:
        profile_alias = resolve_profile_alias(
            core,
            pentry,
            centry,
            provider_alias,
        )

    # Resolve API key alias + envvar
    api_key_alias, api_key_env = resolve_api_key(
        core,
        pentry,
        centry,
        provider_alias,
    )

    backend_identity = pentry.backend
    prof_cfg = pentry.profiles[profile_alias]

    prov_cfg = ProviderConfig(
        alias=provider_alias,
        backend=backend_identity,
        api_key_env=api_key_env,
        model=prof_cfg.model,
    )

    # Merge client behavior defaults + overrides from the base client alias
    client_cfg = resolve_client_behavior(clients_settings, centry)

    # Build an ad-hoc provider backend and OrcaClient for this call only.
    from orchestrai.components.providerkit.factory import build_provider
    from orchestrai.client.client import OrcaClient

    backend = build_provider(prov_cfg)
    return OrcaClient(provider=backend, config=client_cfg)

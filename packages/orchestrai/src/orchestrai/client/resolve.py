# orchestrai/client/resolve.py
from typing import Dict, Tuple

from .conf_models import OrcaClientsSettings, OrcaClientEntry
from .schemas import OrcaClientConfig
from ..components.providerkit.conf_models import (
    ProvidersSettings,
    ProviderSettingsEntry,
)
from .settings_loader import OrcaSettings


def get_client_entry_or_default(
    clients_settings: OrcaClientsSettings,
    client_alias: str,
) -> OrcaClientEntry | None:
    """
    Return the OrcaClientEntry for a given alias, or None for the synthetic
    baseline 'default' client.

    Rules:
      - If client_alias != 'default', the entry MUST exist in CLIENTS; otherwise KeyError.
      - If client_alias == 'default', the entry may be missing; callers then
        synthesize behavior from OrcaClientsSettings.defaults.
    """
    centry = clients_settings.clients.get(client_alias)
    if centry is None and client_alias != "default":
        raise KeyError(f"No client config named '{client_alias}' in CLIENTS")

    return centry


def resolve_provider_alias(
    core: OrcaSettings,
    providers_settings: ProvidersSettings,
    centry: OrcaClientEntry | None,
    client_alias: str,
) -> str:
    """
    Resolve the provider alias for a given client.

    Semantics:
      - If centry.provider is set, it MUST match a provider alias in PROVIDERS.
      - Otherwise:
          DEFAULT_PROVIDER (if valid) → 'default' (if present) → first provider key.
    """
    providers_cfg: Dict[str, ProviderSettingsEntry] = providers_settings.root
    if not providers_cfg:
        raise ValueError(
            "No providers are configured (PROVIDERS is empty). "
            "Configure ORCHESTRAI_PROVIDERS/ORCA_PROVIDERS with at least one provider alias, "
            "or inject an explicit client into the service."
        )

    provider_alias: str | None = None

    if centry is not None and centry.provider:
        if centry.provider in providers_cfg:
            provider_alias = centry.provider
        else:
            raise ValueError(
                f"Client '{client_alias}' references unknown provider alias "
                f"'{centry.provider}'"
            )
    else:
        # No provider set on the client: use defaults.
        default_provider = getattr(core, "DEFAULT_PROVIDER", "default")
        if default_provider in providers_cfg:
            provider_alias = default_provider
        elif "default" in providers_cfg:
            provider_alias = "default"
        else:
            provider_alias = next(iter(providers_cfg.keys()), None)

    if provider_alias is None:
        raise ValueError(
            f"Client '{client_alias}' has no provider specified and no default "
            f"provider could be resolved"
        )

    return provider_alias


def resolve_profile_alias(
    core: OrcaSettings,
    pentry: ProviderSettingsEntry,
    centry: OrcaClientEntry | None,
    provider_alias: str,
) -> str:
    """
    Resolve the provider profile alias for this client/provider combination.

    Semantics:
      - centry.profile, if set, wins.
      - else provider.defaults.profile, if set.
      - else DEFAULT_PROVIDER_PROFILE (if present in profiles).
      - else 'default', if present.
      - else first profile key.
    """
    profiles = pentry.profiles or {}
    profile_alias: str | None = None

    if centry is not None and centry.profile:
        profile_alias = centry.profile
    elif pentry.defaults.profile:
        profile_alias = pentry.defaults.profile
    else:
        default_profile = getattr(core, "DEFAULT_PROVIDER_PROFILE", "default")
        if default_profile in profiles:
            profile_alias = default_profile
        elif "default" in profiles:
            profile_alias = "default"
        else:
            profile_alias = next(iter(profiles.keys()), None)

    if profile_alias is None or profile_alias not in profiles:
        raise ValueError(
            f"Provider '{provider_alias}' has no profile '{profile_alias}'. "
            f"Available: {list(profiles.keys())}"
        )

    return profile_alias


def resolve_api_key(
    core: OrcaSettings,
    pentry: ProviderSettingsEntry,
    centry: OrcaClientEntry | None,
    provider_alias: str,
) -> Tuple[str | None, str | None]:
    """
    Resolve (api_key_alias, api_key_envvar) for the provider/client combo.

    Semantics:
      - If ProviderSettingsEntry.api_key_envvar is a dict:
          - Alias is centry.api_key_alias or DEFAULT_PROVIDER_API_KEY_ALIAS.
          - That alias must exist as a key in the dict.
          - The dict value (envvar name) is returned as api_key_envvar.
      - If api_key_envvar is a str:
          - api_key_alias is None; the str is used as api_key_envvar.
      - If api_key_envvar is None:
          - Both alias and envvar are None.
    """
    api_key_cfg = pentry.api_key_envvar

    api_key_alias: str | None = None
    api_key_env: str | None = None

    if isinstance(api_key_cfg, dict):
        # Choose alias
        api_key_alias = (
            centry.api_key_alias
            if centry is not None and centry.api_key_alias
            else getattr(core, "DEFAULT_PROVIDER_API_KEY_ALIAS", "prod")
        )
        if api_key_alias not in api_key_cfg:
            raise ValueError(
                f"Provider '{provider_alias}' has no API key alias '{api_key_alias}'. "
                f"Available: {list(api_key_cfg.keys())}"
            )
        api_key_env = api_key_cfg[api_key_alias]
    elif isinstance(api_key_cfg, str):
        api_key_env = api_key_cfg
    else:
        api_key_env = None

    return api_key_alias, api_key_env


def resolve_client_behavior(
    clients_settings: OrcaClientsSettings,
    centry: OrcaClientEntry | None,
) -> OrcaClientConfig:
    """
    Merge global client defaults with per-client overrides to produce
    the final OrcaClientConfig (runtime behavior knobs).

    Precedence:
      - per-client override
      - OrcaClientsSettings.defaults
    """
    defaults = clients_settings.defaults

    return OrcaClientConfig(
        max_retries=centry.max_retries
        if centry is not None and centry.max_retries is not None
        else defaults.max_retries,
        timeout_s=centry.timeout_s
        if centry is not None and centry.timeout_s is not None
        else defaults.timeout_s,
        telemetry_enabled=(
            centry.telemetry_enabled
            if centry is not None and centry.telemetry_enabled is not None
            else defaults.telemetry_enabled
        ),
        log_prompts=(
            centry.log_prompts
            if centry is not None and centry.log_prompts is not None
            else defaults.log_prompts
        ),
        raise_on_error=(
            centry.raise_on_error
            if centry is not None and centry.raise_on_error is not None
            else defaults.raise_on_error
        ),
    )


def resolve_client_flags(
    core: OrcaSettings,
    clients_settings: OrcaClientsSettings,
    client_alias: str,
    centry: OrcaClientEntry | None,
) -> tuple[bool, bool, bool]:
    """
    Resolve (is_default, enabled, healthcheck) for a client.

    Semantics:
      - is_default: DEFAULT_CLIENT == client_alias
      - enabled/healthcheck come from the client entry when present.
      - For the synthetic 'default' client (no entry), enabled=True and
        healthcheck=healthcheck_on_start.
    """
    is_default = getattr(core, "DEFAULT_CLIENT", "default") == client_alias

    if centry is not None:
        enabled = centry.enabled
        healthcheck = centry.healthcheck
    else:
        # Synthetic baseline 'default' client
        enabled = True
        healthcheck = getattr(clients_settings, "healthcheck_on_start", True)

    return is_default, enabled, healthcheck
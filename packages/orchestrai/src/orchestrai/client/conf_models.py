# orchestrai/client/conf_models.py
from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from orchestrai.components.providerkit.exceptions import ProviderConfigurationError


# ---------------------------------------------------------------------------
# CLIENT DEFAULTS
# ---------------------------------------------------------------------------
class OrcaClientDefaults(BaseModel):
    """
    Global client-level defaults (NOT provider-level).
    These come from global settings or project settings.

    They do NOT include provider things like model/temp/max_tokens.
    """

    model_config = ConfigDict(extra="forbid")

    timeout_s: float | None = None
    max_retries: int | None = None
    telemetry_enabled: bool | None = None
    log_prompts: bool | None = None
    raise_on_error: bool | None = None


# ---------------------------------------------------------------------------
# A SINGLE CLIENT ENTRY (Orca client alias)
# ---------------------------------------------------------------------------
class OrcaClientEntry(BaseModel):
    """
    Definition of a single Orca client preset.

    This does NOT define backend identity or model/temperature; those belong
    to provider profiles.

    This object binds:
      - provider alias
      - profile alias
      - API key alias (if provider.api_key_envvar is a dict)
      - client-level behaviors
    """

    model_config = ConfigDict(extra="forbid")

    # Provider alias (key in PROVIDERS)
    provider: str | None = None

    # Profile alias (key in PROVIDERS[provider].profiles)
    profile: str | None = None

    # Alias into PROVIDERS[provider].api_key_envvar (if dict)
    api_key_alias: str | None = None

    # Client-side behavior overrides
    timeout_s: float | None = None
    max_retries: int | None = None
    telemetry_enabled: bool | None = None
    log_prompts: bool | None = None
    raise_on_error: bool | None = None

    # Deprecated / no longer used, but kept for guardrails
    enabled: bool = Field(default=True, exclude=True)
    default: bool = Field(default=False, exclude=True)
    healthcheck: bool = Field(default=True, exclude=True)


# ---------------------------------------------------------------------------
# FULL CLIENTS CONFIG (CLIENTS = { alias → OrcaClientEntry })
# ---------------------------------------------------------------------------
class OrcaClientsSettings(BaseModel):
    """
    The full CLIENTS mapping provided in project settings (POD MODE ONLY).

    Special rules:
      - "default" alias is **reserved** for the auto-synthesized client.
      - User-defined CLIENTS MUST NOT contain "default".
      - DEFAULT_CLIENT (global default pointer) can reference any alias OTHER
        than "default" (unless they intend to use the synthesized one).
    """

    model_config = ConfigDict(extra="forbid")

    clients: Dict[str, OrcaClientEntry] = Field(default_factory=dict)
    defaults: OrcaClientDefaults = Field(default_factory=OrcaClientDefaults)

    healthcheck_on_start: bool = True

    @model_validator(mode="after")
    def validate_no_reserved_default(self):
        """
        Enforce strict mode rule:
        CLIENTS MUST NOT define "default".

        The real baseline default client is always auto-synthesized from
        global defaults + provider defaults.
        """
        if "default" in self.clients:
            raise ProviderConfigurationError(
                "CLIENTS['default'] is forbidden. "
                "'default' is a reserved alias for the auto-configured baseline Orca client. "
                "Use DEFAULT_CLIENT to select a different default client alias."
            )
        return self
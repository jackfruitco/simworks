"""Settings loader for client/provider configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..conf.settings import Settings
from ..components.providerkit.conf_models import ProvidersSettings
from .conf_models import OrcaClientsSettings


class OrcaSettings(BaseModel):
    """Structured settings used by the client factory helpers."""

    model_config = ConfigDict(extra="ignore")

    MODE: str = "single"
    CLIENT: str | None = None
    CLIENTS: OrcaClientsSettings = Field(default_factory=OrcaClientsSettings)
    PROVIDERS: ProvidersSettings = Field(default_factory=ProvidersSettings)

    DEFAULT_PROVIDER: str | None = None
    DEFAULT_PROVIDER_PROFILE: str | None = None
    DEFAULT_PROVIDER_API_KEY_ALIAS: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict | None = None) -> "OrcaSettings":
        """Construct settings from an untyped mapping of config values."""

        mapping = mapping or {}
        return cls(**mapping)


def load_orca_settings(mapping: dict | None = None) -> OrcaSettings:
    """Load and normalize Orca settings using the modern settings layer."""

    base = Settings()
    base.update_from_object("orchestrai.settings")
    base.update_from_envvar("ORCHESTRAI_CONFIG_MODULE")

    if mapping:
        base.update_from_mapping(mapping)

    return OrcaSettings.from_mapping(base.as_dict())


__all__ = ["load_orca_settings", "OrcaSettings"]

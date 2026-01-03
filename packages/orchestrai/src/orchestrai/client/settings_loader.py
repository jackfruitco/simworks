"""Settings loader for client/provider configuration."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..conf.settings import Settings
from ..components.providerkit.conf_models import ProvidersSettings
from .conf_models import OrcaClientsSettings


class ClientSettings(BaseModel):
    """Structured settings used by the client factory helpers."""

    model_config = ConfigDict(extra="ignore")

    MODE: str = "single"
    CLIENT: dict | str | None = None
    CLIENTS: OrcaClientsSettings = Field(default_factory=OrcaClientsSettings)
    PROVIDERS: ProvidersSettings = Field(default_factory=ProvidersSettings)

    DEFAULT_PROVIDER: str | None = None
    DEFAULT_PROVIDER_PROFILE: str | None = None
    DEFAULT_PROVIDER_API_KEY_ALIAS: str | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None = None) -> "ClientSettings":
        """Construct settings from an untyped mapping of config values."""

        mapping = dict(mapping or {})
        return cls(**mapping)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClientSettings":
        """Construct settings from a fully prepared ``Settings`` instance."""

        return cls.from_mapping(settings.as_dict())


def _coerce_settings(source: Settings | Mapping[str, Any] | None) -> Settings:
    if isinstance(source, Settings):
        return source

    base = Settings()
    base.update_from_object("orchestrai.settings")
    base.update_from_envvar("ORCHESTRAI_CONFIG_MODULE")

    if source:
        base.update_from_mapping(source)

    return base


def load_client_settings(source: Settings | Mapping[str, Any] | None = None) -> ClientSettings:
    """Normalize client settings, favoring a pre-built ``Settings`` instance."""

    prepared = _coerce_settings(source)
    return ClientSettings.from_settings(prepared)


def load_orca_settings(mapping: Mapping[str, Any] | None = None) -> ClientSettings:
    """Compatibility shim for the legacy OrcaSettings loader."""

    warnings.warn(
        "load_orca_settings is deprecated; use load_client_settings with a Settings instance instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return load_client_settings(mapping)


OrcaSettings = ClientSettings

__all__ = ["load_client_settings", "ClientSettings", "load_orca_settings", "OrcaSettings"]

# orchestrai/components/providerkit/conf_models.py
from __future__ import annotations

from typing import Any, Dict, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

from .exceptions import ProviderConfigurationError
from ...contrib.provider_backends import AVAILABLE_PROVIDER_BACKENDS

__all__ = ("ProvidersSettings", "ProviderSettingsEntry")


# ---------------------------------------------------------------------
# Profile (provider-side model settings)
# ---------------------------------------------------------------------
class ProviderProfileSettings(BaseModel):
    """
    Provider-side tuning preset.

    All fields are optional here; Pydantic + global_settings can provide
    actual defaults so configs can leave things as None when desired.
    """

    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None

    # Allow provider-specific extra params (e.g. `response_format`, `top_p`, etc.)
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------
# Default selections
# ---------------------------------------------------------------------
class ProviderDefaults(BaseModel):
    """
    Defaults for a provider alias.

    Currently only tracks the default profile alias; other defaults
    (like API key alias) are handled at the client/global level.
    """

    profile: str | None = None


# ---------------------------------------------------------------------
# Entry for a *single provider alias*
# ---------------------------------------------------------------------
class ProviderSettingsEntry(BaseModel):
    """
    Configuration for a single provider alias in PROVIDERS.

    "provider alias" = the key in the PROVIDERS dict.
    "backend identity" = dot-separated registry identity, e.g. "openai.responses.backend".
    """

    # Allow both BACKEND (Django-style) and backend (field name) via populate_by_name.
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # Backend identity, e.g. "openai.responses.backend"
    # May be provided directly via BACKEND, or derived from PROVIDER + SURFACE.
    backend: str | None = Field(None, alias="BACKEND")
    # Optional sugar: PROVIDER + SURFACE can be used instead of BACKEND,
    # and will be normalized into a backend identity string.
    provider: str | None = Field(None, alias="PROVIDER")
    surface: str | None = Field(None, alias="SURFACE")

    # API key envvar configuration:
    #   - str: single envvar name
    #   - dict[str, str | None]: envvar names keyed by an opaque alias ("prod", "dev", "tenant1", ...)
    #
    # Keys are aliases only; the library does NOT hard-code environment semantics.
    api_key_envvar: str | Dict[str, str | None] | None = None

    # Provider profiles (model/temperature/max_output_tokens/extra knobs)
    profiles: Dict[str, ProviderProfileSettings] = Field(default_factory=dict)

    # Provider defaults (currently: default profile alias)
    defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)

    # -------------------------
    # Validate BACKEND identity
    # -------------------------
    @field_validator("backend")
    @classmethod
    def validate_backend_identity(cls, v: str) -> str:
        """
        Ensure BACKEND is a proper provider identity like:
            'openai.responses.backend'
        """
        parts = v.split(".")
        if len(parts) != 3:
            raise ProviderConfigurationError(
                f"BACKEND must be 'namespace.kind.name', e.g. 'openai.responses.backend' (got {v!r})"
            )

        namespace, kind, name = parts

        if namespace not in AVAILABLE_PROVIDER_BACKENDS:
            raise ProviderConfigurationError(
                f"Invalid provider BACKEND namespace {namespace!r}. "
                f"Expected one of: {', '.join(sorted(AVAILABLE_PROVIDER_BACKENDS))}"
            )

        if name != "backend":
            raise ProviderConfigurationError(
                f"BACKEND identity must end in '.backend' (got {v!r})"
            )

        return v

    @model_validator(mode="after")
    def normalize_backend(self) -> "ProviderSettingsEntry":
        """
        Normalize provider/backend configuration.

        Semantics:
          - If BACKEND is explicitly provided, it wins and is validated as a full
            identity string like 'openai.responses.backend'.
          - Otherwise, both PROVIDER and SURFACE must be provided, and a backend
            identity string 'PROVIDER.SURFACE.backend' is synthesized and validated.
        """
        # If backend is already set, just validate it (field_validator may have
        # already done this, but we enforce once more for safety).
        if self.backend:
            self.backend = self.validate_backend_identity(self.backend)
            return self

        # No BACKEND: PROVIDER must be set; SURFACE may default to "default"
        if not self.provider:
            raise ProviderConfigurationError(
                "When BACKEND is not provided, PROVIDER must be set."
            )

        surface = self.surface or "default"
        backend = f"{self.provider}.{surface}.backend"
        self.backend = self.validate_backend_identity(backend)
        return self

    # -----------------------------------------
    # Validate api_key_envvar
    # -----------------------------------------
    @field_validator("api_key_envvar")
    @classmethod
    def validate_api_key_envvar(
        cls, v: str | Dict[str, str | None] | None
    ) -> str | Dict[str, str | None] | None:
        """
        Ensure api_key_envvar is either:
          - None
          - a single envvar name (str)
          - a dict of alias -> envvar name (str or None)
        """
        if isinstance(v, dict):
            for alias, envvar in v.items():
                if not alias or not isinstance(alias, str):
                    raise ValueError(
                        f"api_key_envvar aliases must be non-empty strings (got {alias!r})"
                    )
                if envvar is not None and not isinstance(envvar, str):
                    raise ValueError(
                        f"api_key_envvar[{alias!r}] must be a str or None (got {type(envvar)!r})"
                    )
        elif v is not None and not isinstance(v, str):
            raise ValueError(
                f"api_key_envvar must be a str, dict, or None (got {type(v)!r})"
            )

        return v

    # -----------------------------------------
    # Validate default profile
    # -----------------------------------------
    @field_validator("defaults", mode="after")
    @classmethod
    def validate_defaults_exist(
        cls, v: ProviderDefaults, info
    ) -> ProviderDefaults:
        data: Mapping[str, Any] = info.data
        profs: Dict[str, ProviderProfileSettings] = data.get("profiles", {})

        if v.profile and v.profile not in profs:
            raise ValueError(
                f"Default profile {v.profile!r} not found in 'profiles'"
            )

        return v


# ---------------------------------------------------------------------
# Top-level settings: provider alias -> ProviderSettingsEntry
# ---------------------------------------------------------------------
class ProvidersSettings(RootModel[Dict[str, ProviderSettingsEntry]]):
    """
    Top-level PROVIDERS settings.

    Example:

        PROVIDERS = {
            "default": {
                "backend": "openai.responses.backend",  # or: "PROVIDER": "openai", "SURFACE": "responses",
                "api_key_envvar": {
                    "prod": "ORCA_PROVIDER_API_KEY",
                    "dev": "ORCA_PROVIDER_API_KEY_DEV",
                },
                "profiles": {
                    "default": {
                        "model": "gpt-5-mini",
                        "temperature": 0.2,
                        "max_output_tokens": 2048,
                    },
                    "low_cost": {
                        "model": "gpt-4o-mini",
                    },
                },
                "defaults": {
                    "profile": "default",
                },
            },
        }

    Aliases are arbitrary user-defined keys (provider aliases).
    """

    def __init__(self, root: Dict[str, ProviderSettingsEntry] | None = None):
        """Allow `ProvidersSettings()` to mean an empty providers mapping."""
        super().__init__(root=root or {})

    @model_validator(mode="after")
    def validate_aliases(self) -> "ProvidersSettings":
        data = self.root

        for alias in data.keys():
            if not alias or not isinstance(alias, str):
                raise ValueError("Provider aliases must be non-empty strings")

        return self
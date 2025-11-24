# simcore_ai/providers/factory.py
"""
simcore_ai.providers.factory
============================

Provider registry and factory functions.

Responsibilities:
- Maintain an in-process registry mapping provider *keys* (e.g., "openai") to concrete
  BaseProvider subclasses.
- Expose helpers to register provider classes and to construct provider instances
  from validated configuration objects.
- Integrate with tracing to aid observability during provider lookup/creation.

Notes:
- This module consumes **AIProviderConfig** from `simcore_ai.client.schemas`.
- Provider *identity* (used in logs/telemetry) is derived from the vendor key and the
  optional `label` via `semantic_provider_name(key, label)`, and passed to the provider
  constructor as `name`.
"""


from typing import Dict, Type

from simcore_ai.components.providerkit.base import BaseProvider
from simcore_ai.registry.exceptions import (
    RegistryError,
    RegistryDuplicateError,
    RegistryLookupError,
)
from ..tracing import service_span_sync
from simcore_ai.client.schemas import AIProviderConfig, semantic_provider_name

# In-process provider registry: key -> provider class
_PROVIDER_REGISTRY: Dict[str, Type[BaseProvider]] = {}


def register_provider(name: str, provider_cls: Type[BaseProvider]) -> None:
    """
    Register a provider class under a lowercase key.

    Safe to call at import-time from provider packages. Idempotent if the same
    class is registered again under the same key; raises on collisions.
    """
    with service_span_sync(
            "simcore.providers.register",
            attributes={
                "simcore.provider_name": name,
                "simcore.provider_cls": f"{provider_cls.__module__}.{provider_cls.__name__}",
            },
    ):
        key = (name or "").lower().strip()
        if not key:
            raise RegistryError("Provider name cannot be empty.")
        if key in _PROVIDER_REGISTRY:
            # Allow idempotent registration of the same class; block collisions
            if _PROVIDER_REGISTRY[key] is not provider_cls:
                raise RegistryDuplicateError(
                    f"Provider '{key}' already registered with a different class."
                )
            return
        _PROVIDER_REGISTRY[key] = provider_cls


def get_provider_class(name: str) -> Type[BaseProvider]:
    """
    Look up the concrete provider class registered under `name` (case-insensitive).

    Raises:
        RegistryLookupError: if no provider class is registered under the given key.
    """
    key = (name or "").lower().strip()
    with service_span_sync(
            "simcore.providers.get_class",
            attributes={"simcore.provider_name": name},
    ):
        try:
            return _PROVIDER_REGISTRY[key]
        except KeyError:
            raise RegistryLookupError(
                f"Unknown AI provider: {name!r}. Registered: {list(_PROVIDER_REGISTRY.keys())}"
            )


def create_provider(config: AIProviderConfig) -> BaseProvider:
    """
    Construct and return a concrete `BaseProvider` instance from a validated
    `AIProviderConfig`.

    Expected behavior:
    - Compute a semantic provider name for observability using the vendor key and label.
    - Instantiate the registered provider class with a minimal, explicit set of kwargs:
      `api_key`, `base_url`, `default_model`, `timeout_s`, and `name`.
    - Provider-specific defaults are applied by the provider's own `__init__`.

    Args:
        config: Effective provider configuration (optionally merged with client overrides).

    Returns:
        BaseProvider: an instantiated provider ready for use.
    """
    with service_span_sync(
            "simcore.providers.create",
            attributes={
                "simcore.provider_name": config.provider,
                "simcore.model": getattr(config, "model", None) or "<unspecified>",
                "simcore.base_url.set": bool(getattr(config, "base_url", None)),
                "simcore.timeout": getattr(config, "timeout_s", None),
                "simcore.provider_label": getattr(config, "label", None) or "",
            },
    ):
        cls = get_provider_class(config.provider)
        semantic_name = semantic_provider_name(config.provider, getattr(config, "label", None))

        # Providers should accept these kwargs; unknown extras are not passed here.
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            default_model=config.model,
            timeout_s=config.timeout_s,
            name=semantic_name,
            provider_key=config.provider,
            provider_label=getattr(config, "label", None),
        )


# ---- Optional: Eagerly register built-in providers if they are available ----
# Keep these imports isolated so the core doesn't hard-depend on any one SDK.
try:
    # OpenAI provider lives in simcore_ai/providers/openai/base.py
    from .openai.openai import OpenAIProvider  # type: ignore

    register_provider("openai", OpenAIProvider)
except Exception:
    # Silently ignore to avoid hard dependency if OpenAI extras aren't installed.
    pass

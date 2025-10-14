# simcore_ai/providers/factory.py
from __future__ import annotations

from typing import Dict, Type, Optional

from ..types import AIProviderConfig
from .base import BaseProvider
from ..tracing import service_span_sync
from simcore_ai.exceptions import RegistryError, RegistryDuplicateError, RegistryLookupError


# In-process provider registry
_PROVIDER_REGISTRY: Dict[str, Type[BaseProvider]] = {}


def register_provider(name: str, provider_cls: Type[BaseProvider]) -> None:
    """
    Register a provider class under a lowercase key.
    Safe to call at import-time from provider packages.
    """
    with service_span_sync(
        "ai.providers.register",
        attributes={
            "ai.provider_name": name,
            "ai.provider_cls": f"{provider_cls.__module__}.{provider_cls.__name__}",
        },
    ):
        key = name.lower().strip()
        if not key:
            raise RegistryError("Provider name cannot be empty.")
        if key in _PROVIDER_REGISTRY:
            # Allow idempotent registration of the same class; block collisions
            if _PROVIDER_REGISTRY[key] is not provider_cls:
                raise RegistryDuplicateError(f"Provider '{key}' already registered with a different class.")
            return
        _PROVIDER_REGISTRY[key] = provider_cls


def get_provider_class(name: str) -> Type[BaseProvider]:
    key = (name or "").lower().strip()
    with service_span_sync(
        "ai.providers.get_class",
        attributes={"ai.provider_name": name},
    ):
        try:
            return _PROVIDER_REGISTRY[key]
        except KeyError:
            raise RegistryLookupError(
                f"Unknown AI provider: {name!r}. Registered: {list(_PROVIDER_REGISTRY.keys())}"
            )


def create_provider(config: AIProviderConfig) -> BaseProvider:
    """
    Construct a ProviderBase subclass from AIProviderConfig.
    Provider-specific defaults (e.g., base_url) should be applied by the provider __init__.
    """
    with service_span_sync(
        "ai.providers.create",
        attributes={
            "ai.provider_name": config.provider,
            "ai.model": getattr(config, "model", None) or "<unspecified>",
            "ai.base_url.set": bool(getattr(config, "base_url", None)),
            "ai.timeout": getattr(config, "timeout_s", None),
        },
    ):
        cls = get_provider_class(config.provider)
        # Providers should accept these kwargs but can ignore unsupported ones.
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            default_model=config.model,
            timeout_s=config.timeout_s,
            image_model=config.image_model,
            image_format=config.image_format,
            image_size=config.image_size,
            image_quality=config.image_quality,
            image_output_compression=config.image_output_compression,
            image_background=config.image_background,
            image_moderation=config.image_moderation,
        )


# ---- Optional: Eagerly register built-in providers if they are available ----
# Keep these imports isolated so the core doesn't hard-depend on any one SDK.
try:
    # Example: OpenAI provider in your tree at simcore_ai/providers/openai/client.py
    from .openai.client import OpenAIProvider  # type: ignore

    register_provider("openai", OpenAIProvider)
except Exception:
    pass
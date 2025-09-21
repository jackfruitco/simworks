# simcore/ai/bootstrap.py
from __future__ import annotations

import importlib
import inspect
import pathlib
import pkgutil
from typing import Optional

from django.conf import settings

from .client import AIClient
from .providers.base import ProviderBase

_ai_client: Optional[AIClient] = None
_default_model: Optional[str] = None

_providers_path = pathlib.Path(__file__).parent / "providers"

SUPPORTED_PROVIDERS = [
    mod.name
    for mod in pkgutil.iter_modules([str(_providers_path)])
    if not mod.ispkg and not mod.name.startswith("_") and mod.name != "base"
]


# Dynamically load and build a provider from its module name
def _build_provider_from_module(provider_key: str) -> ProviderBase:
    """
    Dynamically import simcore.ai.providers.<provider_key> and return an AIProvider instance.
    The provider module may optionally expose `build_from_settings(settings) -> AIProvider`.
    Otherwise, we will search for a subclass of AIProvider and try to construct it
    with common kwargs. If neither path works, raise a clear error.
    """
    module_path = f"{__package__}.providers.{provider_key}"
    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise RuntimeError(f"Provider module not found for key '{provider_key}': {module_path}") from e

    # Preferred: factory function defined by the provider module
    factory = getattr(mod, "build_from_settings", None)
    if callable(factory):
        provider = factory(settings)
        if not isinstance(provider, ProviderBase):
            raise RuntimeError(f"Provider factory for '{provider_key}' did not return an AIProvider instance")
        return provider

    # Fallback: find a subclass of AIProvider in the module
    provider_cls = None
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if obj is not ProviderBase and issubclass(obj, ProviderBase) and obj.__module__ == mod.__name__:
            provider_cls = obj
            break

    if provider_cls is None:
        raise RuntimeError(
            f"No AIProvider subclass found in module '{module_path}' and no build_from_settings(settings) provided."
        )

    # Attempt a generic construction for common providers (api_key/base_url/timeout/name)
    try:
        # Try the most common signature first
        provider = provider_cls(
            api_key=getattr(settings, "AI_API_KEY", None),  # may be unused by non-OpenAI providers
            base_url=getattr(settings, "OPENAI_BASE_URL", None),
            timeout=getattr(settings, "OPENAI_TIMEOUT_S", 30),
            name=provider_key,
        )
        if not isinstance(provider, ProviderBase):
            raise TypeError("Constructed provider is not an AIProvider")
        return provider
    except TypeError:
        # As a last resort, try parameterless construction with a name only
        try:
            provider = provider_cls(name=provider_key)  # type: ignore[call-arg]
            if not isinstance(provider, ProviderBase):
                raise TypeError("Constructed provider is not an AIProvider")
            return provider
        except Exception as e:
            raise RuntimeError(
                f"Unable to construct provider '{provider_key}'. Define build_from_settings(settings) in '{module_path}'."
            ) from e


def init_ai_singleton() -> AIClient:
    global _ai_client, _default_model
    if _ai_client is not None:
        return _ai_client

    if settings.AI_PROVIDER not in SUPPORTED_PROVIDERS:
        raise RuntimeError(f"Unsupported AI_PROVIDER={settings.AI_PROVIDER}")

    provider = _build_provider_from_module(settings.AI_PROVIDER)
    _ai_client = AIClient(provider=provider)
    _default_model = settings.AI_DEFAULT_MODEL
    return _ai_client


def get_ai_client() -> AIClient:
    # Lazy; works in Django, ASGI, and Celery workers
    return init_ai_singleton()


def get_default_model() -> str:
    if _default_model is None:
        init_ai_singleton()
    return _default_model  # type: ignore[return-value]

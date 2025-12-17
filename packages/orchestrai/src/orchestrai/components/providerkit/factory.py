# orchestrai/components/providerkit/factory.py

import logging
import os

from .provider import BaseProvider, ProviderConfig
from .exceptions import ProviderConfigurationError
from .utils import get_backend_class
from ...tracing import service_span_sync

logger = logging.getLogger(__name__)


def build_provider(cfg: ProviderConfig) -> BaseProvider:
    """
    Build a concrete provider backend from a ProviderConfig.

    Django-style semantics:

      - `cfg.alias` is a user-facing alias / connection name
          e.g. "default", "openai", "openai-low-cost".
        It is *not* used for identity resolution.

      - `cfg.backend` is the *backend identity string* registered in
        the provider_backends registry, e.g. "openai.responses.backend".
        This value is expected to be fully normalized by the config layer
        (e.g. from BACKEND or from PROVIDER/SURFACE in settings); the factory
        does not perform any additional parsing beyond identity resolution.

      - The backend class is resolved via the registry using `cfg.backend`
        and then instantiated with a kwargs dict that:

          * passes `alias` through unchanged (if provided)
          * leaves all other fields (model, base_url, timeout_s, etc.)
            for concrete providers to consume via their own __init__/**kwargs.

      - Concrete providers are expected to accept **kwargs and call
        BaseProvider.__init__(alias=..., provider=..., api_key=..., profile=..., ...)
        internally, using their own defaults for provider/api_surface unless
        explicitly overridden.
    """
    if not isinstance(cfg, ProviderConfig):
        raise TypeError(f"build_provider expected ProviderConfig, got {type(cfg)}")

    backend_identity = cfg.backend

    # -----------------------------
    # Look up provider class by identity
    # -----------------------------
    with service_span_sync(
        "orchestrai.providers.lookup_class",
        attributes={
            "simcore.provider.backend_identity": backend_identity,
            "simcore.provider.alias": cfg.alias,
        },
    ):
        provider_cls: type[BaseProvider] = get_backend_class(backend_identity)

    # -----------------------------
    # Prepare kwargs for __init__
    # -----------------------------
    cfg_dict = cfg.model_dump()

    # Extract the two special fields we *don't* want to pass through as-is.
    # - backend: used only for registry lookup, not as a runtime kwarg.
    # - alias: forwarded as alias if present.
    cfg_dict.pop("backend", None)
    alias = cfg_dict.pop("alias", None)

    init_kwargs = cfg_dict

    # Resolve the API key from an explicitly configured env var if provided.
    api_key_env = init_kwargs.get("api_key_env")
    resolved_api_key = init_kwargs.get("api_key") or (
        api_key_env and os.getenv(str(api_key_env))
    )
    if resolved_api_key is not None:
        init_kwargs["api_key"] = resolved_api_key

    if alias is not None:
        init_kwargs.setdefault("alias", alias)

    # NOTE:
    # We intentionally do NOT set `provider=backend` here.
    # `backend` is an identity string like "openai.responses.backend", not
    # the provider slug ("openai"). Concrete backend classes are responsible
    # for setting their own `provider` / `api_surface` defaults.

    # Concrete providers are expected to accept **kwargs and call
    # BaseProvider.__init__(...) internally.
    with service_span_sync(
        "orchestrai.providers.build_instance",
        attributes={
            "simcore.provider.class": f"{provider_cls.__module__}.{provider_cls.__name__}",
            "simcore.provider.alias": alias or "",
            "simcore.provider.backend_identity": backend_identity or "",
        },
    ):
        try:
            provider = provider_cls(**init_kwargs)
        except TypeError as exc:
            # Add context; this is the most common failure point if __init__ signature
            # doesn't line up with ProviderConfig fields.
            raise ProviderConfigurationError(
                f"Failed to construct provider '{provider_cls.__name__}' "
                f"for alias '{cfg.alias}': {exc}"
            ) from exc

    logger.debug(
        "Built provider instance %r for alias '%s' (backend_identity=%s)",
        provider,
        cfg.alias,
        backend_identity,
    )
    return provider

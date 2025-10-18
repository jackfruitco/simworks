# simcore_ai/registry.py
from __future__ import annotations

from threading import RLock
from typing import Dict, Optional, Mapping, Any

from .client import AIClient
from simcore_ai.exceptions.registry_exceptions import (
    RegistryError, RegistryDuplicateError, RegistryLookupError
)
from simcore_ai.providers.factory import create_provider
from simcore_ai.types import AIClientConfig, AIProviderConfig
from simcore_ai.tracing import service_span_sync


_clients: Dict[str, AIClient] = {}
_default_name: Optional[str] = None
_lock = RLock()


def _normalize_segment(s: Optional[str]) -> str:
    if not s:
        return "default"
    return s.strip().replace(" ", "-").lower()


def _default_name_for(cfg: AIProviderConfig) -> str:
    return f"{_normalize_segment(cfg.provider)}-{_normalize_segment(cfg.model)}"


def create_client(
    cfg: AIProviderConfig,
    name: str | None = None,
    *,
    make_default: bool = False,
    replace: bool = False,
    client_config: Optional[AIClientConfig] = None,
) -> AIClient:
    """
    Create and register an AIClient under a name.
    - If name is None, uses "{provider}-{model or default}".
    - If replace is False and name exists, raises.
    - If make_default is True, sets this as the default client.
    """
    with service_span_sync(
        "ai.clients.create",
        attributes={
            "ai.provider_name": cfg.provider,
            "ai.model": cfg.model or "<unspecified>",
            "ai.client_name": name or _default_name_for(cfg),
            "ai.make_default": bool(make_default),
            "ai.replace": bool(replace),
        },
    ):
        provider = create_provider(cfg)
        client = AIClient(provider=provider, config=client_config or AIClientConfig())

        cname = name or _default_name_for(cfg)
        with _lock:
            if not replace and cname in _clients:
                raise RegistryDuplicateError(f"AI client '{cname}' already exists.")
            _clients[cname] = client

            global _default_name
            if make_default or _default_name is None:
                _default_name = cname
        return client


def create_client_from_dict(
    cfg_dict: Mapping[str, Any],
    name: str | None = None,
    *,
    make_default: bool = False,
    replace: bool = False,
    client_config: Optional[AIClientConfig] = None,
) -> AIClient:
    """
    Convenience: build AIProviderConfig from a plain dict, then create the client.
    """
    with service_span_sync(
        "ai.clients.create_from_dict",
        attributes={
            "ai.client_name": name or "<auto>",
            "ai.make_default": bool(make_default),
            "ai.replace": bool(replace),
        },
    ):
        cfg = AIProviderConfig(**cfg_dict)  # type: ignore[arg-type]
        return create_client(
            cfg,
            name=name,
            make_default=make_default,
            replace=replace,
            client_config=client_config,
        )


def get_ai_client(name: str | None = None, provider: str | None = None) -> AIClient:
    """
    Resolve a client by:
      1) name (if provided),
      2) provider (if unique),
      3) default client (if set),
    otherwise raise a helpful error.
    """
    with service_span_sync(
        "ai.client.resolve",
        attributes={
            "ai.client_name": name or "",
            "ai.provider_name": provider or "",
        },
    ) as span:
        with _lock:
            if name:
                try:
                    resolved = _clients[name]
                    try:
                        span.set_attribute("ai.client.resolved_name", name)
                        span.set_attribute("ai.provider.resolved", getattr(resolved.provider, "name", None) or "")
                    except Exception:
                        pass
                    return resolved
                except KeyError:
                    raise RegistryLookupError(f"No AI client named '{name}'. Available: {list(_clients)}")

            if provider:
                matches = [c for c in _clients.values() if getattr(c.provider, "name", None) == provider]
                if len(matches) == 1:
                    resolved = matches[0]
                    try:
                        # find its registry name (reverse lookup)
                        for k, v in _clients.items():
                            if v is resolved:
                                span.set_attribute("ai.client.resolved_name", k)
                                break
                        span.set_attribute("ai.provider.resolved", provider)
                    except Exception:
                        pass
                    return resolved
                if len(matches) > 1:
                    raise RegistryError(
                        f"Multiple clients for provider '{provider}'. Specify a name. "
                        f"Available: {list(_clients)}"
                    )
                raise RegistryLookupError(f"No clients for provider '{provider}'.")

            if _default_name and _default_name in _clients:
                resolved = _clients[_default_name]
                try:
                    span.set_attribute("ai.client.resolved_name", _default_name)
                    span.set_attribute("ai.provider.resolved", getattr(resolved.provider, "name", None) or "")
                except Exception:
                    pass
                return resolved

            raise RegistryLookupError(
                "No AI clients have been created. "
                "Create one with create_client(...) or bootstrap from your framework."
            )


def list_clients() -> Dict[str, AIClient]:
    with _lock:
        with service_span_sync("ai.clients.list", attributes={"ai.clients.count": len(_clients)}):
            return dict(_clients)


def set_default_client(name: str) -> None:
    with _lock:
        with service_span_sync("ai.clients.set_default", attributes={"ai.client_name": name}):
            if name not in _clients:
                raise RegistryLookupError(f"No AI client named '{name}'")
            global _default_name
            _default_name = name


def clear_clients() -> None:
    """Clear all clients and default — useful in tests."""
    with _lock:
        with service_span_sync("ai.clients.clear", attributes={"ai.clients.prev_count": len(_clients)}):
            _clients.clear()
            global _default_name
            _default_name = None
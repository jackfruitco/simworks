# simcore_ai/client/registry.py
"""
simcore_ai.client.registry
==========================

In-process registry for `AIClient` instances.

Responsibilities
----------------
- Create and register `AIClient` objects from effective provider configurations.
- Maintain a default client pointer (until the Django glue selects one deterministically).
- Resolve clients by explicit name, by provider semantic name, or fall back to default.
- Provide light diagnostics for setup flows (e.g., client_count, is_configured).

Notes
-----
- This module consumes the **new** `AIProviderConfig` from `simcore_ai.client.schemas`.
- The effective provider configuration (including overrides and API key resolution)
  should typically be computed by the Django glue before calling `create_client`.
- Default selection policy is orchestrated in the Django setup layer; `make_default`
  remains supported but is best avoided in application code.
"""
from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import Dict, Optional, Any

from simcore_ai.client.schemas import AIProviderConfig, AIClientConfig
from simcore_ai.providers.factory import create_provider
from simcore_ai.registry.exceptions import (
    RegistryError,
    RegistryDuplicateError,
    RegistryLookupError,
)
from simcore_ai.tracing import service_span_sync
from .client import AIClient

_clients: Dict[str, AIClient] = {}
_default_name: Optional[str] = None
_lock = RLock()


def _normalize_segment(s: Optional[str]) -> str:
    """Normalize a segment for auto-generated names (lowercase, dashes, fallback 'default')."""
    if not s:
        return "default"
    return s.strip().replace(" ", "-").lower()


def _default_name_for(cfg: AIProviderConfig) -> str:
    """Construct an automatic client name from provider key and model."""
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
    Create and register an `AIClient` under a name.

    Behavior:
    - If `name` is None, uses "{provider}-{model or default}".
    - If `replace` is False and name exists, raises `RegistryDuplicateError`.
    - If `make_default` is True, sets this as the default client (note: default
      selection is normally orchestrated in the Django setup layer).

    Args:
        cfg: Effective provider configuration (merged & resolved).
        name: Registry name for this client.
        make_default: Whether to set this client as default immediately.
        replace: If True, replaces an existing client with the same name.
        client_config: Runtime knobs for the client (timeout, retries, etc.).

    Returns:
        The newly registered `AIClient`.
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

            # Maintain default pointer if requested or not yet set.
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
    Convenience helper: build `AIProviderConfig` from a plain dict, then create the client.

    Note:
        In the new architecture, the Django integration typically constructs an
        effective `AIProviderConfig` directly and calls `create_client`. This function
        is retained for convenience and test helpers.
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


def get_default_client() -> AIClient:
    """
    Return the current default AIClient instance.

    Raises:
        RegistryLookupError: if no default client is registered.
    """
    with _lock:
        return _get_default_client_locked()


def _get_default_client_locked() -> AIClient:
    """Internal: return default client, assuming _lock is already held."""
    if _default_name and _default_name in _clients:
        return _clients[_default_name]
    raise RegistryLookupError(
        "No default AI client is set. Ensure one client is marked 'default': True or that setup chose a default."
    )


def get_ai_client(name: str | None = None, provider: str | None = None) -> AIClient:
    """
    Resolve a client by:
      1) explicit `name` (if provided),
      2) `provider` semantic name (if unique among clients),
      3) default client (if set),
    otherwise raise a helpful error.

    Args:
        name: The registry name of the client.
        provider: The semantic provider name (e.g., "openai" or "openai:prod").
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
                        span.set_attribute(
                            "ai.provider.resolved",
                            getattr(resolved.provider, "name", None) or "",
                        )
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

            resolved = _get_default_client_locked()
            try:
                span.set_attribute("ai.client.resolved_name", _default_name or "")
                span.set_attribute(
                    "ai.provider.resolved",
                    getattr(resolved.provider, "name", None) or "",
                )
            except Exception:
                pass
            return resolved


def list_clients() -> Dict[str, AIClient]:
    """Return a shallow copy of the registered clients mapping."""
    with _lock:
        with service_span_sync("ai.clients.list", attributes={"ai.clients.count": len(_clients)}):
            return dict(_clients)


def set_default_client(name: str) -> None:
    """Set the default client by registry name."""
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


# ---- Diagnostics helpers -----------------------------------------------------


def client_count() -> int:
    """Return the number of registered clients (for setup idempotency checks)."""
    with _lock:
        return len(_clients)


def is_configured() -> bool:
    """Return True if at least one client is registered."""
    return client_count() > 0

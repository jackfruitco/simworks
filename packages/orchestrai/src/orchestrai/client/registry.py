# orchestrai/client/registry.py
"""
orchestrai.client.registry
==========================

In-process registry for `OrcaClient` instances.

Responsibilities
----------------
- Create and register `OrcaClient` objects from effective backend configurations.
- Maintain a default client pointer (until the Django glue selects one deterministically).
- Resolve clients by explicit name, by backend semantic name, or fall back to default.
- Provide light diagnostics for setup flows (e.g., client_count, is_configured).

Notes
-----
- This module consumes the **new** ProviderConfig from orchestrai.components.providerkit.
- The effective backend configuration (including overrides and API key resolution)
  should typically be computed by the Django glue before calling `create_client`.
- Default selection policy is orchestrated in the Django setup layer; `make_default`
  remains supported but is best avoided in application code.
"""


from collections.abc import Mapping
from threading import RLock
from typing import Dict, Optional, Any

from orchestrai.client.schemas import OrcaClientConfig
from orchestrai.components.providerkit import ProviderConfig
from orchestrai.components.providerkit.factory import build_provider
from orchestrai.registry.exceptions import (
    RegistryError,
    RegistryDuplicateError,
    RegistryLookupError,
)
from orchestrai.tracing import service_span_sync
from .client import OrcaClient

_clients: Dict[str, OrcaClient] = {}
_default_name: Optional[str] = None
_lock = RLock()


def _normalize_segment(s: Optional[str]) -> str:
    """Normalize a segment for auto-generated names (lowercase, dashes, fallback 'default')."""
    if not s:
        return "default"
    return s.strip().replace(" ", "-").lower()


def _default_name_for(cfg: ProviderConfig) -> str:
    """Construct an automatic client name from backend key and model."""
    return f"{_normalize_segment(cfg.backend)}-{_normalize_segment(cfg.model)}"


def create_client(
        cfg: ProviderConfig,
        name: str | None = None,
        *,
        make_default: bool = False,
        replace: bool = False,
        client_config: Optional[OrcaClientConfig] = None,
) -> OrcaClient:
    """
    Create and register an `OrcaClient` under a name.

    Behavior:
    - If `name` is None, uses "{backend}-{model or default}".
    - If `replace` is False and name exists, raises `RegistryDuplicateError`.
    - If `make_default` is True, sets this as the default client (note: default
      selection is normally orchestrated in the Django setup layer).

    Args:
        cfg: Effective backend configuration (merged & resolved).
        name: Registry name for this client.
        make_default: Whether to set this client as default immediately.
        replace: If True, replaces an existing client with the same name.
        client_config: Runtime knobs for the client (timeout, retries, etc.).

    Returns:
        The newly registered `OrcaClient`.
    """
    with service_span_sync(
            "simcore.clients.create",
            attributes={
                "simcore.provider_name": cfg.backend,
                "simcore.model": cfg.model or "<unspecified>",
                "simcore.client_name": name or _default_name_for(cfg),
                "simcore.make_default": bool(make_default),
                "simcore.replace": bool(replace),
            },
    ):
        provider = build_provider(cfg)
        client = OrcaClient(provider=provider, config=client_config or OrcaClientConfig())

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
        client_config: Optional[OrcaClientConfig] = None,
) -> OrcaClient:
    """
    Convenience helper: build `ProviderConfig` from a plain dict, then create the client.

    Note:
        In the new architecture, the Django integration typically constructs an
        effective `ProviderConfig` directly and calls `create_client`. This function
        is retained for convenience and test helpers.
    """
    with service_span_sync(
            "simcore.clients.create_from_dict",
            attributes={
                "simcore.client_name": name or "<auto>",
                "simcore.make_default": bool(make_default),
                "simcore.replace": bool(replace),
            },
    ):
        cfg = ProviderConfig(**cfg_dict)  # type: ignore[arg-type]
        return create_client(
            cfg,
            name=name,
            make_default=make_default,
            replace=replace,
            client_config=client_config,
        )


def get_default_client() -> OrcaClient:
    """
    Return the current default OrcaClient instance.

    Raises:
        RegistryLookupError: if no default client is registered.
    """
    with _lock:
        return _get_default_client_locked()

def _get_default_client_locked() -> OrcaClient:
    """Internal: return default client, assuming _lock is already held."""
    global _default_name

    # Happy path
    if _default_name and _default_name in _clients:
        return _clients[_default_name]

    # If nothing is registered, be explicit about the real problem.
    if not _clients:
        raise RegistryLookupError(
            "No default AI client is set and no clients are registered. "
            "Ensure orchestrai.client.registry.create_client(...) is called during startup."
        )

    # Prefer conventional name when present.
    if "default" in _clients:
        _default_name = "default"
        return _clients[_default_name]

    # If exactly one client exists, it's safe to use it.
    if len(_clients) == 1:
        _default_name = next(iter(_clients))
        return _clients[_default_name]

    # Otherwise, force caller to choose.
    raise RegistryLookupError(
        "No default AI client is set. Ensure one client is marked 'default': True "
        f"or that setup chose a default. Available: {list(_clients)}"
    )

def get_ai_client(name: str | None = None, provider: str | None = None) -> OrcaClient:
    """
    Resolve a client by:
      1) explicit `name` (if provided),
      2) `backend` semantic name (if unique among clients),
      3) default client (if set),
    otherwise raise a helpful error.

    Args:
        name: The registry name of the client.
        provider: The backend slug (e.g., "openai"), matching ProviderConfig.backend / BaseProvider.provider.
    """
    with service_span_sync(
            "simcore.client.resolve",
            attributes={
                "simcore.client_name": name or "",
                "simcore.provider_name": provider or "",
            },
    ) as span:
        with _lock:
            if name:
                try:
                    resolved = _clients[name]
                    try:
                        span.set_attribute("simcore.client.resolved_name", name)
                        span.set_attribute(
                            "simcore.backend.resolved",
                            getattr(resolved.provider, "provider", None) or "",
                        )
                    except Exception:
                        pass
                    return resolved
                except KeyError:
                    raise RegistryLookupError(f"No AI client named '{name}'. Available: {list(_clients)}")

            if provider:
                matches = [c for c in _clients.values() if getattr(c.provider, "provider", None) == provider]
                if len(matches) == 1:
                    resolved = matches[0]
                    try:
                        # find its registry name (reverse lookup)
                        for k, v in _clients.items():
                            if v is resolved:
                                span.set_attribute("simcore.client.resolved_name", k)
                                break
                        span.set_attribute("simcore.backend.resolved", provider)
                    except Exception:
                        pass
                    return resolved
                if len(matches) > 1:
                    raise RegistryError(
                        f"Multiple clients for backend '{provider}'. Specify a name. "
                        f"Available: {list(_clients)}"
                    )
                raise RegistryLookupError(f"No clients for backend '{provider}'.")

            resolved = _get_default_client_locked()
            try:
                span.set_attribute("simcore.client.resolved_name", _default_name or "")
                span.set_attribute(
                    "simcore.backend.resolved",
                    getattr(resolved.provider, "provider", None) or "",
                )
            except Exception:
                pass
            return resolved


def list_clients() -> Dict[str, OrcaClient]:
    """Return a shallow copy of the registered clients mapping."""
    with _lock:
        with service_span_sync("simcore.clients.list", attributes={"simcore.clients.count": len(_clients)}):
            return dict(_clients)


def set_default_client(name: str) -> None:
    """Set the default client by registry name."""
    with _lock:
        with service_span_sync("simcore.clients.set_default", attributes={"simcore.client_name": name}):
            if name not in _clients:
                raise RegistryLookupError(f"No AI client named '{name}'")
            global _default_name
            _default_name = name


def clear_clients() -> None:
    """Clear all clients and default — useful in tests."""
    with _lock:
        with service_span_sync("simcore.clients.clear", attributes={"simcore.clients.prev_count": len(_clients)}):
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

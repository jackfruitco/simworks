# simcore_ai/identity/registry_resolvers.py
"""
Central helper utilities for resolving registry entries by identity.

This module provides internal helpers to extract registries and resolve entries
based on identity-like inputs. It is the single implementation used by
`Identity.try_resolve(...)` to avoid duplicating coercion logic.

Accepted identity inputs:
  • Identity instance
  • dot string "namespace.kind.name"
  • tuple[str, str, str]  (namespace, kind, name)
  • any object with an `.identity` attribute containing one of the above
"""

from __future__ import annotations

import logging
from typing import TypeVar, runtime_checkable, Protocol, Optional, Any

from simcore_ai.identity.utils import coerce_identity_key

logger = logging.getLogger(__name__)

T = TypeVar("T")


@runtime_checkable
class _RegistryProto(Protocol[T]):
    """Private protocol describing a registry with a get((ns, kind, name)) -> Optional[T]."""


@runtime_checkable
class _HasRegistry(Protocol):
    """Private protocol describing a type that exposes a registry."""

    @classmethod
    def get_registry(cls) -> _RegistryProto[Any]: ...


def _extract_registry(obj: Any) -> Optional[_RegistryProto[Any]]:
    """
    Private helper to extract a registry instance from the given object.

    Accepts either a registry instance (has a callable .get method) or a class/type
    exposing a registry via a callable .get_registry() class method.

    Returns the registry instance or None if extraction fails (no exceptions raised).
    """
    # Concrete registry instance?
    if hasattr(obj, "get") and callable(getattr(obj, "get")):
        return obj  # type: ignore[return-value]
    # A class/type that exposes a registry?
    if hasattr(obj, "get_registry") and callable(getattr(obj, "get_registry")):
        try:
            reg = obj.get_registry()  # type: ignore[attr-defined]
            if hasattr(reg, "get") and callable(getattr(reg, "get")):
                return reg
        except Exception:
            logger.debug("Failed to obtain registry from %r", obj, exc_info=True)
    return None


def try_resolve_from_ident(target: Any, registry_or_type: Any) -> Optional[Any]:
    """
    Resolve a registry entry from an identity-like input.

    Args:
        target:
            Identity-like input:
              - Identity instance
              - "namespace.kind.name" string
              - (namespace, kind, name) tuple
              - object with `.identity` containing one of the above
        registry_or_type:
            A registry instance exposing `.get(tuple[str, str, str]) -> Optional[Any]`,
            or a class/type that provides `@classmethod get_registry() -> registry`.

    Returns:
        The resolved registry entry or None if resolution fails.
    """
    # 1) Extract a registry instance
    registry = _extract_registry(registry_or_type)
    if registry is None:
        return None

    # 2) Coerce the identity-like input to (ns, kind, name)
    key = None

    # If object has an `.identity`, prefer that first
    if hasattr(target, "identity"):
        ident_val = getattr(target, "identity")
        key = coerce_identity_key(ident_val)

    # Fallback: coerce the target itself
    if key is None:
        key = coerce_identity_key(target)

    if key is None:
        return None

    # 3) Query the registry
    try:
        return registry.get(key)
    except Exception:
        logger.debug("Failed to resolve key %r from registry %r", key, registry, exc_info=True)
        return None

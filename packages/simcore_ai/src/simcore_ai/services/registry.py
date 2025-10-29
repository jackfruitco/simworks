"""
Service class registry for SimCore AI.

This module provides a minimal, framework-agnostic registry for service classes,
keyed by (namespace:str, kind:str, name:str) tuples.

Key format:
    (namespace, kind, name): all are non-empty strings.

Collision policy:
    When registering a service with a key that already exists and is associated
    with a different class, a DuplicateServiceIdentityError is raised.
    The registry does not rename or resolve collisions automatically.

Exported symbols:
    - ServiceRegistry
    - DuplicateServiceIdentityError
"""

import logging
import os
import threading
from collections.abc import Iterable
from typing import Optional, Type

from simcore_ai.identity import parse_dot_identity

_logger = logging.getLogger(__name__)


class DuplicateServiceIdentityError(Exception):
    """Raised when attempting to register a service class with a duplicate identity."""


class ServiceRegistry:
    """
    Framework-agnostic registry for service classes, keyed by (namespace, kind, name).
    """

    _store: dict[tuple[str, str, str], Type] = {}
    _lock = threading.RLock()

    @classmethod
    def _debug_from_env(cls) -> bool:
        """Return True if SIMCORE_AI_DEBUG is set to a truthy value."""
        return bool(os.environ.get("SIMCORE_AI_DEBUG", "").strip())

    @classmethod
    def has(cls, namespace: str, kind: str, name: str) -> bool:
        """Return True if a service is registered under the given (namespace, kind, name)."""
        with cls._lock:
            return (namespace, kind, name) in cls._store

    @classmethod
    def _identity_for_cls(cls, service_cls: Type) -> tuple[str, str, str]:
        """
        Derive (namespace, kind, name) from class attributes.
        Accepts either explicit 'namespace', 'kind', 'name' attributes,
        or a dot-separated 'identity' attribute.
        Raises TypeError if not found.
        """
        if hasattr(service_cls, "namespace") and hasattr(service_cls, "kind") and hasattr(service_cls, "name"):
            namespace = getattr(service_cls, "namespace")
            kind = getattr(service_cls, "kind")
            name = getattr(service_cls, "name")
            if not all(isinstance(x, str) and x for x in (namespace, kind, name)):
                raise TypeError(f"Service class {service_cls!r} has invalid identity attributes.")
            return (namespace, kind, name)
        elif hasattr(service_cls, "identity"):
            ident = getattr(service_cls, "identity")
            if not isinstance(ident, str):
                raise TypeError(f"Service class {service_cls!r} has non-string identity attribute.")
            return parse_dot_identity(ident)
        raise TypeError(f"Service class {service_cls!r} missing identity attributes.")

    @classmethod
    def register(cls, service_cls: Type, *, debug: Optional[bool] = None) -> None:
        """
        Register a service class.

        Raises DuplicateServiceIdentityError if a different class is already registered
        under the same identity.

        If the same class is already registered under the identity, this is a no-op.

        If 'debug' is not supplied, uses SIMCORE_AI_DEBUG environment variable.
        """
        ident = cls._identity_for_cls(service_cls)
        debug_mode = debug if debug is not None else cls._debug_from_env()

        with cls._lock:
            prev = cls._store.get(ident)
            if prev is not None and prev is not service_cls:
                raise DuplicateServiceIdentityError(
                    f"Service identity {ident} already registered with a different class {prev}"
                )
            if prev is service_cls:
                # already registered, no-op
                return
            cls._store[ident] = service_cls
            _logger.info(f"Service {ident} registered: {service_cls}")

    @classmethod
    def get(cls, identity: tuple[str, str, str]) -> Optional[Type]:
        """Return the registered service class for the key, or None if not found."""
        with cls._lock:
            return cls._store.get(identity)

    @classmethod
    def get_str(cls, key: str) -> Optional[Type]:
        """Return the service class for a dot-identity string, or None if not found."""
        ident = parse_dot_identity(key)
        return cls.get(ident)

    @classmethod
    def require(cls, identity: tuple[str, str, str]) -> Type:
        """Return the registered service class for the key, raising KeyError if missing."""
        svc = cls.get(identity)
        if svc is None:
            _logger.warning(f"Service {identity} not found in registry")
            raise KeyError(f"Service {identity} not found in registry")
        return svc

    @classmethod
    def require_str(cls, key: str) -> Type:
        """Return the service class for a dot-identity string, raising KeyError if missing."""
        ident = parse_dot_identity(key)
        return cls.require(ident)

    @classmethod
    def all(cls) -> Iterable[Type]:
        """Return all registered service classes."""
        with cls._lock:
            return list(cls._store.values())

    @classmethod
    def clear(cls) -> None:
        """Remove all registered service classes."""
        with cls._lock:
            cls._store.clear()
            _logger.info("ServiceRegistry cleared")


__all__ = ["ServiceRegistry", "DuplicateServiceIdentityError"]

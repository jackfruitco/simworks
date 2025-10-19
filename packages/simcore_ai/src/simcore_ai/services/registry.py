"""
Service class registry for SimCore AI.

This module provides a minimal, framework-agnostic registry for service classes,
keyed by (origin:str, bucket:str, name:str) tuples.

Key format:
    (origin, bucket, name): all are non-empty strings.

Collision policy:
    When registering a service with a key that already exists, the core resolver
    (`resolve_collision`) is used to determine if the new class should override the old.

Exported symbols:
    - ServicesRegistry
"""

import logging
import os
import threading
from typing import Optional, Type, Iterable

from simcore_ai.identity import resolve_collision, parse_dot_identity

_logger = logging.getLogger(__name__)


class ServicesRegistry:
    """
    Framework-agnostic registry for service classes, keyed by (origin, bucket, name).
    """
    _store: dict[tuple[str, str, str], Type] = {}
    _lock = threading.RLock()

    @classmethod
    def _debug_from_env(cls) -> bool:
        """Return True if SIMCORE_AI_DEBUG is set to a truthy value."""
        return bool(os.environ.get("SIMCORE_AI_DEBUG", "").strip())

    @classmethod
    def has(cls, origin: str, bucket: str, name: str) -> bool:
        """Return True if a service is registered under the given (origin, bucket, name)."""
        with cls._lock:
            return (origin, bucket, name) in cls._store

    @classmethod
    def _identity_for_cls(cls, service_cls: Type) -> tuple[str, str, str]:
        """
        Derive (origin, bucket, name) from class attributes.
        Accepts either explicit 'origin', 'bucket', 'name' attributes,
        or a dot-separated 'identity' attribute.
        Raises TypeError if not found.
        """
        if hasattr(service_cls, "origin") and hasattr(service_cls, "bucket") and hasattr(service_cls, "name"):
            origin = getattr(service_cls, "origin")
            bucket = getattr(service_cls, "bucket")
            name = getattr(service_cls, "name")
            if not all(isinstance(x, str) and x for x in (origin, bucket, name)):
                raise TypeError(f"Service class {service_cls!r} has invalid identity attributes.")
            return (origin, bucket, name)
        elif hasattr(service_cls, "identity"):
            ident = getattr(service_cls, "identity")
            if not isinstance(ident, str):
                raise TypeError(f"Service class {service_cls!r} has non-string identity attribute.")
            return parse_dot_identity(ident)
        raise TypeError(f"Service class {service_cls!r} missing identity attributes.")

    @classmethod
    def register(cls, service_cls: Type, *, debug: Optional[bool] = None) -> None:
        """
        Register a service class, resolving collisions if necessary.
        If 'debug' is not supplied, uses SIMCORE_AI_DEBUG environment variable.
        """
        ident = cls._identity_for_cls(service_cls)
        debug_mode = debug if debug is not None else cls._debug_from_env()

        def exists(t):
            return t in cls._store

        new_ident = resolve_collision(
            "service", ident, debug=debug_mode, exists=exists
        )
        with cls._lock:
            prev = cls._store.get(new_ident)
            cls._store[new_ident] = service_cls
            if prev and prev is not service_cls:
                _logger.info(f"Service {new_ident} replaced {prev} with {service_cls}")
            elif not prev:
                _logger.info(f"Service {new_ident} registered: {service_cls}")

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
            _logger.info("ServicesRegistry cleared")


__all__ = ["ServicesRegistry"]

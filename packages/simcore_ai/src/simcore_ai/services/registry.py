from __future__ import annotations

"""
Service class registry (AIv3 / Identity-first).

- Stores **service classes** keyed by canonical identity tuple `(namespace, kind, name)`.
- Classes MUST expose `identity: Identity`. No legacy fallbacks are supported.

Public API (mirrors other registries):
    ServiceRegistry.register(cls, replace=False)
    ServiceRegistry.get(identity)        # tuple3 | "ns.kind.name" | Identity
    ServiceRegistry.require(identity)
    ServiceRegistry.all()                # -> tuple[type, ...]
    ServiceRegistry.identities()         # -> tuple[tuple[str, str, str], ...]
    ServiceRegistry.clear()
"""

import logging
import threading
from typing import ClassVar

from simcore_ai.identity.base import Identity, IdentityKey
from simcore_ai.identity import coerce_identity_key
from simcore_ai.identity.exceptions import IdentityValidationError
from simcore_ai.tracing import service_span_sync

__all__ = [
    "ServiceRegistry",
    "DuplicateServiceIdentityError",
    "ServiceNotFoundError",
]

logger = logging.getLogger(__name__)


# -------------------- Errors --------------------

class DuplicateServiceIdentityError(Exception):
    """Raised when attempting to register a different class at an existing identity."""


class ServiceNotFoundError(KeyError):
    """Raised when a service class is not found in the registry."""


# -------------------- Registry --------------------

class ServiceRegistry:
    """Global registry for service **classes** keyed by (namespace, kind, name)."""

    _store: dict[tuple[str, str, str], type] = {}
    _lock: ClassVar[threading.RLock] = threading.RLock()

    # ------------------------------------------------------------------
    # Registration (public) → strict + idempotent
    # ------------------------------------------------------------------
    @classmethod
    def register(
        cls,
        candidate: type,
        *,
        replace: bool = False,
    ) -> None:
        """Register a **service class**.

        Requirements:
          • `candidate.identity` MUST be an `Identity` instance.

        Semantics:
          • Idempotent if the same class is re-registered at the same identity.
          • If a different class owns the same identity:
              - replace=True  → overwrite (warn)
              - replace=False → raise DuplicateServiceIdentityError
        """
        ident = getattr(candidate, "identity", None)
        if not isinstance(ident, Identity):
            raise TypeError(
                f"{getattr(candidate, '__name__', candidate)!r} must define `identity: Identity`."
            )
        cls._register(candidate, replace=replace)

    # ------------------------------------------------------------------
    # Registration (private write path)
    # ------------------------------------------------------------------
    @classmethod
    def _register(
        cls,
        candidate: type,
        *,
        replace: bool = False,
    ) -> None:
        """Private single write path with dupe detection."""
        with cls._lock:
            identity: Identity = candidate.identity  # type: ignore[attr-defined]
            key = identity.as_tuple3
            ident_str = identity.as_str

            existing = cls._store.get(key)

            if existing is None:
                cls._store[key] = candidate
                logger.info("service.register %s -> %s", ident_str, candidate.__name__)
                return

            if existing is candidate:
                if replace:
                    logger.info("service.register.replace %s (same class)", ident_str)
                    cls._store[key] = candidate
                # else no-op
                return

            # Collision with a different class
            if replace:
                logger.warning(
                    "service.register.replace.collision %s (old=%s, new=%s)",
                    ident_str, getattr(existing, "__name__", existing), candidate.__name__,
                )
                cls._store[key] = candidate
                return

            raise DuplicateServiceIdentityError(
                f"Service identity already registered: {ident_str} "
                f"(existing={getattr(existing, '__name__', existing)}, new={candidate.__name__})"
            )

    # ---------------- lookups ----------------
    @classmethod
    def get(cls, identity: IdentityKey) -> type | None:
        """Retrieve a registered service class by identity.

        Accepts:
          • tuple[str, str, str] (namespace, kind, name)
          • Identity (object exposing `.as_tuple3`)
          • str ("namespace.kind.name")
        """
        ident_tuple3 = coerce_identity_key(identity)
        if ident_tuple3 is None:
            logger.warning("%s could not resolve Service from identity %r", cls.__name__, identity)
            return None

        ident_str = ".".join(ident_tuple3)
        with service_span_sync("ai.service.registry.get", attributes={"identity": ident_str}):
            with cls._lock:
                return cls._store.get(ident_tuple3)

    @classmethod
    def require(cls, identity: IdentityKey) -> type:
        """Like `get` but raises `ServiceNotFoundError` if not found."""
        ident_tuple3 = coerce_identity_key(identity)
        if ident_tuple3 is None:
            raise IdentityValidationError(f"Invalid identity key: {identity!r}")
        ident_str = ".".join(ident_tuple3)
        with service_span_sync("ai.service.registry.require", attributes={"identity": ident_str}):
            svc_cls = cls.get(ident_tuple3)
            if svc_cls is None:
                raise ServiceNotFoundError(f"Service not registered: {ident_str}")
            return svc_cls

    # ---- introspection ----
    @classmethod
    def all(cls) -> tuple[type, ...]:
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def identities(cls) -> tuple[tuple[str, str, str], ...]:
        with cls._lock:
            return tuple(cls._store.keys())

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            count = len(cls._store)
            cls._store.clear()
            logger.debug("service.registry.clear count=%d", count)

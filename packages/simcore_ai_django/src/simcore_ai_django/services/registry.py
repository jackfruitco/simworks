# simcore_ai_django/services/registry.py
from __future__ import annotations

"""
Django Service Registry (class registry).

This registry stores **service classes** keyed by the finalized identity tuple
`(namespace, kind, name)`. It enforces duplicate vs collision behavior and
exposes a simple resolution API.

Policy (per implementation plan):
- Identity tuple is `(namespace, kind, name)`; values are assumed to be fully
  derived/validated *before* registration (decorators perform derivation).
- **Duplicate**: same class attempts to register with the same identity → skip
  idempotently (DEBUG log only).
- **Collision**: *different* class attempts to register the same identity →
  behavior controlled by `SIMCORE_COLLISIONS_STRICT` (default True):
    * True  → raise `IdentityCollisionError`
    * False → log WARNING and record for Django system checks (no mutation).
- **Invalid identity** (wrong arity / non-str / empty) → always raise
  `IdentityValidationError`.
- Validation is delegated to simcore_ai.identity (Identity/coerce_identity_key); this module does not implement its own validators.

Note: No Django ORM is used here; this is a pure in-process registry.
"""

from dataclasses import dataclass
import logging
import threading
from typing import Any, Iterable, Optional, Tuple, Type

from simcore_ai.identity import Identity
from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = [
    "IdentityCollisionError",
    "IdentityValidationError",
    "Registered",
    "ServiceRegistry",
    "services",
]


# -------------------------
# Exceptions
# -------------------------

class IdentityCollisionError(Exception):
    """Raised when a different class attempts to register an existing identity."""


class IdentityValidationError(Exception):
    """Raised when identity is malformed (arity/empties/non-strings)."""


# -------------------------
# Data structures
# -------------------------

@dataclass(frozen=True)
class Registered:
    identity: Tuple[str, str, str]
    cls: Type[Any]


# -------------------------
# Registry
# -------------------------

class ServiceRegistry:
    """Registry of service **classes** keyed by `(namespace, kind, name)` tuples."""

    def __init__(self) -> None:
        self._by_id: dict[Tuple[str, str, str], Type[Any]] = {}
        self._by_cls: dict[Type[Any], Tuple[str, str, str]] = {}
        self._collisions: set[Tuple[str, str, str]] = set()
        self._lock = threading.RLock()

        # Read strictness once per process; default True
        strict_default = True
        self._strict: bool = bool(getattr(settings, "SIMCORE_COLLISIONS_STRICT", strict_default))

    # ---- helpers ----
    @staticmethod
    def _validate_identity(identity: Tuple[str, str, str] | str | Identity) -> Tuple[str, str, str]:
        """Coerce and validate an identity via the centralized Identity API.

        Accepts tuple3, canonical dot string, or Identity object.
        Returns the normalized (namespace, kind, name) tuple.
        Raises IdentityValidationError on failure.
        """
        try:
            ident = Identity.get_for(identity)  # strict coercion + validation
        except Exception as e:
            raise IdentityValidationError(
                f"Invalid identity {identity!r}: {e}"
            ) from e
        return ident.as_tuple3

    # ---- registration API ----
    def maybe_register(self, identity: Tuple[str, str, str] | str | Identity, cls: Type[Any]) -> None:
        """
        Register a service class if not already registered.

        - Duplicate (same class + same identity): skip (DEBUG)
        - Collision (different class + same identity): raise when strict, else warn
        """
        ns, kd, nm = self._validate_identity(identity)
        key = (ns, kd, nm)

        with self._lock:
            # Same class already registered (idempotent under autoreload)
            prev = self._by_cls.get(cls)
            if prev == key:
                logger.debug("service.duplicate-class-same-identity %s %s", cls, key)
                return

            existing = self._by_id.get(key)
            if existing is None:
                # First registration
                self._by_id[key] = cls
                self._by_cls[cls] = key
                logger.debug("service.registered %s -> %s", ".".join(key), cls.__name__)
                return

            if existing is cls:
                # Same class attempting to register again with same key
                self._by_cls[cls] = key  # ensure mapping is present
                logger.debug("service.duplicate-class-same-identity %s %s", cls, key)
                return

            # Collision: different class, same identity
            self._collisions.add(key)
            msg = f"Service identity collision {key} between {existing} and {cls}"
            if self._strict:
                logger.error("service.collision %s", msg)
                raise IdentityCollisionError(msg)
            else:
                logger.warning("service.collision %s", msg)
                # In non-strict mode we do NOT mutate identity here. Decorators
                # may choose to rewrite name and retry. We record for checks.
                return

    def resolve(self, identity: Tuple[str, str, str] | str | Identity) -> Optional[Type[Any]]:
        ns, kd, nm = self._validate_identity(identity)
        key = (ns, kd, nm)
        with self._lock:
            return self._by_id.get(key)

    def resolve_str(self, identity: str) -> Optional[Type[Any]]:
        key = self._validate_identity(identity)
        with self._lock:
            return self._by_id.get(key)

    def require(self, identity: Tuple[str, str, str] | str | Identity) -> Type[Any]:
        key = self._validate_identity(identity)
        with self._lock:
            cls = self._by_id.get(key)
            if cls is None:
                raise KeyError(f"Service not registered for identity: {'.'.join(key)}")
            return cls

    def require_str(self, identity: str) -> Type[Any]:
        return self.require(identity)

    def list(self) -> Iterable[Registered]:
        with self._lock:
            return tuple(Registered(k, v) for k, v in self._by_id.items())

    def collisions(self) -> Iterable[Tuple[str, str, str]]:
        with self._lock:
            return tuple(self._collisions)


# Singleton instance for Django layer
services = ServiceRegistry()

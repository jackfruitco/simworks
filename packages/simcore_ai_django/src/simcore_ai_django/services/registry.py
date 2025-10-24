# packages/simcore_ai_django/src/simcore_ai_django/services/registry.py
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

Note: No Django ORM is used here; this is a pure in-process registry.
"""

from dataclasses import dataclass
import logging
import threading
from typing import Any, Iterable, Optional, Tuple, Type

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
    def _validate_identity(identity: Tuple[str, str, str]) -> Tuple[str, str, str]:
        try:
            ns, kd, nm = identity
        except Exception:
            raise IdentityValidationError(
                f"Identity must be a 3-tuple (namespace, kind, name); got {identity!r}"
            )
        for label, val in (("namespace", ns), ("kind", kd), ("name", nm)):
            if not isinstance(val, str):
                raise IdentityValidationError(f"{label} must be str; got {type(val)!r}")
            if not val.strip():
                raise IdentityValidationError(f"{label} cannot be empty")
        return ns, kd, nm

    # ---- registration API ----
    def maybe_register(self, identity: Tuple[str, str, str], cls: Type[Any]) -> None:
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
                # annotate for introspection
                setattr(cls, "namespace", ns)
                setattr(cls, "kind", kd)
                setattr(cls, "name", nm)
                setattr(cls, "identity", key)
                logger.debug("service.registered %s", ".".join(key))
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

    def resolve(self, identity: Tuple[str, str, str]) -> Optional[Type[Any]]:
        ns, kd, nm = self._validate_identity(identity)
        key = (ns, kd, nm)
        with self._lock:
            return self._by_id.get(key)

    def list(self) -> Iterable[Registered]:
        with self._lock:
            return tuple(Registered(k, v) for k, v in self._by_id.items())

    def collisions(self) -> Iterable[Tuple[str, str, str]]:
        with self._lock:
            return tuple(self._collisions)


# Singleton instance for Django layer
services = ServiceRegistry()

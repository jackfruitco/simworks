# simcore_ai_django/promptkit/registry.py
from __future__ import annotations

from simcore_ai.identity.exceptions import IdentityCollisionError

"""
Django Prompt Section Registry (class registry).

This registry stores **prompt section classes** keyed by the finalized identity
`(namespace, kind, name)`. It enforces duplicate vs collision behavior and
exposes a simple resolution API.

Policy (per implementation plan):
- Identity key is `(namespace, kind, name)`; values are assumed to be fully
  derived/validated *before* registration by decorators/resolvers.
- **Duplicate**: same class attempts to register with the same identity → skip
  idempotently (DEBUG log only).
- **Collision**: *different* class attempts to register the same identity →
  behavior controlled by `SIMCORE_COLLISIONS_STRICT` (default True):
    * True  → raise `IdentityCollisionError`
    * False → log WARNING and record for Django system checks (no mutation).
- **Invalid identity** (wrong arity / non-str / empty) → always raise
  `IdentityValidationError`.

IMPORTANT:
- This registry **does not mutate** the registered classes (no stamping of
  `namespace/kind/name/identity`). Identity is owned by resolvers/decorators.
- No Django ORM is used here; this is a pure in-process registry.
"""

from dataclasses import dataclass
import logging
import threading
from typing import Any, Iterable, Optional, Tuple, Type

from django.conf import settings

# Identity primitives/utilities (centralized in core)
from simcore_ai.identity import IdentityKey, coerce_identity_key

logger = logging.getLogger(__name__)

__all__ = [
    "Registered",
    "PromptSectionRegistry",
    "prompt_sections",
]


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

class PromptSectionRegistry:
    """Registry of prompt section **classes** keyed by `(namespace, kind, name)` tuples."""

    def __init__(self) -> None:
        self._by_id: dict[IdentityKey, Type[Any]] = {}
        self._by_cls: dict[Type[Any], IdentityKey] = {}
        self._collisions: set[IdentityKey] = set()
        self._lock = threading.RLock()

        # Read strictness once per process; default True
        strict_default = True
        self._strict: bool = bool(getattr(settings, "SIMCORE_COLLISIONS_STRICT", strict_default))

    # ---- registration API ----
    def maybe_register(self, identity: IdentityKey, cls: Type[Any]) -> None:
        """
        Register a prompt section class if not already registered.

        - Duplicate (same class + same identity): skip (DEBUG)
        - Collision (different class + same identity): raise when strict, else warn
        """
        key = coerce_identity_key(identity)

        with self._lock:
            # Same class already registered (idempotent under autoreload)
            prev = self._by_cls.get(cls)
            if prev == key:
                logger.debug("prompt_section.duplicate-class-same-identity %s %s", cls, key)
                return

            existing = self._by_id.get(key)
            if existing is None:
                # First registration
                self._by_id[key] = cls
                self._by_cls[cls] = key
                logger.debug("prompt_section.registered %s", ".".join(key))
                return

            if existing is cls:
                # Same class attempting to register again with same key
                self._by_cls[cls] = key  # ensure mapping is present
                logger.debug("prompt_section.duplicate-class-same-identity %s %s", cls, key)
                return

            # Collision: different class, same identity
            self._collisions.add(key)
            msg = f"Prompt section identity collision {key} between {existing} and {cls}"
            if self._strict:
                logger.error("prompt_section.collision %s", msg)
                raise IdentityCollisionError(msg)
            else:
                logger.warning("prompt_section.collision %s", msg)
                # In non-strict mode we do NOT mutate or replace. We record for checks.
                return

    def resolve(self, identity: IdentityKey) -> Optional[Type[Any]]:
        key = coerce_identity_key(identity)
        with self._lock:
            return self._by_id.get(key)

    def require(self, identity: IdentityKey) -> Type[Any]:
        key = coerce_identity_key(identity)
        with self._lock:
            cls = self._by_id.get(key)
            if cls is None:
                raise KeyError(f"PromptSection not registered: {'.'.join(key)}")
            return cls

    def resolve_str(self, identity_str: str) -> Optional[Type[Any]]:
        return self.resolve(identity_str)

    def list(self) -> Iterable[Registered]:
        with self._lock:
            return tuple(Registered(k, v) for k, v in self._by_id.items())

    def collisions(self) -> Iterable[IdentityKey]:
        with self._lock:
            return tuple(self._collisions)

    def clear(self) -> None:
        """Testing helper to wipe the registry safely."""
        with self._lock:
            self._by_id.clear()
            self._by_cls.clear()
            self._collisions.clear()


# Singleton instance for the Django layer
prompt_sections = PromptSectionRegistry()

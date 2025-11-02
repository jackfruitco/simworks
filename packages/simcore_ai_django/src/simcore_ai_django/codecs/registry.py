# simcore_ai_django/codecs/registry.py
from __future__ import annotations

"""
Django Codec Registry (class registry, async-first batch helpers).

This registry stores **codec classes** keyed by the finalized identity tuple
`(namespace, kind, name)`. It enforces duplicate vs. collision behavior and
exposes batch persistence helpers with async-first surfaces.

Terminology & policy (per implementation plan):
- Identity tuple is `(namespace, kind, name)`; values are assumed to be fully
  derived/validated *before* registration (decorators perform derivation).
- **Duplicate**: same class attempts to register with the same identity → skip
  idempotently (DEBUG log only).
- **Collision**: *different* class attempts to register the same identity →
  behavior controlled by `SIMCORE_COLLISIONS_STRICT` (default True):
    * True  → raise `IdentityCollisionError`
    * False → log WARNING and record for Django system checks
      (decorators may opt-in to perform deterministic rename before retrying)
- **Invalid identity** (wrong arity / non-str / empty) → always raise
  `IdentityValidationError`.

Batch helpers:
- `apersists_batch(items, *, ctx=None)` is the primary async API. It will
  resolve each item's codec class by its `identity` (tuple) attribute or by a
  callable `identity_tuple()` and invoke the codec instance's `apersist` if
  present, otherwise `persist` (wrapped via `sync_to_async`).
- `persist_batch` is a sync adapter calling the async version via `async_to_sync`.

Note: No Django models or ORM are assumed in this file; we only use
`transaction.atomic` for correctness when callers perform DB writes inside
codecs.
"""

from dataclasses import dataclass
import logging
import threading
from typing import Any, Iterable

from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction
from django.conf import settings

from simcore_ai.identity import Identity

logger = logging.getLogger(__name__)

__all__ = [
    "IdentityCollisionError",
    "IdentityValidationError",
    "Registered",
    "CodecRegistry",
    "codecs",
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
    identity: tuple[str, str, str]
    cls: type[Any]


# -------------------------
# Registry
# -------------------------

class CodecRegistry:
    """Registry of codec **classes** keyed by `(namespace, kind, name)` tuples."""

    def __init__(self) -> None:
        self._by_id: dict[tuple[str, str, str], type[Any]] = {}
        self._by_cls: dict[type[Any], tuple[str, str, str]] = {}
        self._collisions: set[tuple[str, str, str]] = set()
        self._lock = threading.RLock()

        # Read strictness once per process; default True
        strict_default = True
        self._strict: bool = bool(getattr(settings, "SIMCORE_COLLISIONS_STRICT", strict_default))

    # ---- helpers ----
    @staticmethod
    def _validate_identity(identity: tuple[str, str, str]) -> tuple[str, str, str]:
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
    def maybe_register(self, identity: tuple[str, str, str], cls: type[Any]) -> None:
        """
        Register a codec class if not already registered.

        - Duplicate (same class + same identity): skip (DEBUG)
        - Collision (different class + same identity): raise when strict, else warn
        """
        ns, kd, nm = self._validate_identity(identity)
        key = (ns, kd, nm)

        with self._lock:
            # Same class already registered (idempotent under autoreload)
            prev = self._by_cls.get(cls)
            if prev == key:
                logger.debug("codec.duplicate-class-same-identity %s %s", cls, key)
                return

            existing = self._by_id.get(key)
            if existing is None:
                # First registration
                self._by_id[key] = cls
                self._by_cls[cls] = key

                # Optional guard: if the class exposes a derived identity tuple, warn on mismatch
                try:
                    derived = None
                    if hasattr(cls, "identity_as_tuple3") and callable(getattr(cls, "identity_as_tuple3")):
                        derived = cls.identity_as_tuple3()  # type: ignore[attr-defined]
                    elif hasattr(cls, "identity") and isinstance(getattr(cls, "identity"), Identity):
                        derived = getattr(cls, "identity").as_tuple3  # type: ignore[assignment]
                    if isinstance(derived, tuple) and len(derived) == 3 and derived != key:
                        logger.warning("codec.identity.mismatch class=%s registered=%s derived=%s", cls, key, derived)
                except Exception:
                    # Best effort only
                    pass

                logger.debug("codec.registered %s", ".".join(key))
                return

            if existing is cls:
                # Same class attempting to register again with same key
                self._by_cls[cls] = key  # ensure mapping is present
                logger.debug("codec.duplicate-class-same-identity %s %s", cls, key)
                return

            # Collision: different class, same identity
            self._collisions.add(key)
            msg = f"Codec identity collision {key} between {existing} and {cls}"
            if self._strict:
                logger.error("codec.collision %s", msg)
                raise IdentityCollisionError(msg)
            else:
                logger.warning("codec.collision %s", msg)
                # In non-strict mode we do NOT mutate identity here. Decorators
                # may choose to rewrite name and retry. We record for checks.
                return

    def resolve(self, identity: tuple[str, str, str]) -> type[Any] | None:
        ns, kd, nm = self._validate_identity(identity)
        key = (ns, kd, nm)
        with self._lock:
            return self._by_id.get(key)

    def list(self) -> Iterable[Registered]:
        with self._lock:
            return tuple(Registered(k, v) for k, v in self._by_id.items())

    def collisions(self) -> Iterable[tuple[str, str, str]]:
        with self._lock:
            return tuple(self._collisions)

    # ---- batch persistence (async-first) ----
    async def apersists_batch(self, items: Iterable[Any], *, ctx: dict | None = None) -> list[Any]:
        """
        Persist a batch of items in a single transaction (call-order semantics).

        For each item:
          - read `identity` (tuple) attribute or call `identity_tuple()` if present
          - resolve registered codec class and instantiate it
          - prefer `apersist` if available; otherwise call `persist` via `sync_to_async`
        """
        ctx = ctx or {}
        saved: list[Any] = []

        def _read_identity(it_: Any) -> tuple[str, str, str]:
            ident = getattr(it_, "identity", None)
            if isinstance(ident, Identity):
                return ident.as_tuple3
            if isinstance(ident, tuple) and len(ident) == 3 and all(isinstance(x, str) for x in ident):
                return ident  # type: ignore[return-value]
            if callable(getattr(it_, "identity_tuple", None)):
                t = it_.identity_tuple()  # type: ignore[attr-defined]
                if isinstance(t, tuple) and len(t) == 3 and all(isinstance(x, str) for x in t):
                    return t
            raise IdentityValidationError(f"Item {it_!r} does not expose an identity tuple")

        async def _persist_one(it_: Any) -> Any:
            key = self._validate_identity(_read_identity(it_))
            cls = self.resolve(key)
            if cls is None:
                raise LookupError(f"No codec registered for identity {key}")
            codec = cls()
            if hasattr(codec, "apersist") and callable(codec.apersist):  # type: ignore[attr-defined]
                return await codec.apersist(it_, ctx=ctx)  # type: ignore[attr-defined]
            # Fallback to sync persist under thread-sensitive wrapper
            if hasattr(codec, "persist") and callable(codec.persist):  # type: ignore[attr-defined]
                return await sync_to_async(codec.persist, thread_sensitive=True)(it_,
                                                                                 ctx=ctx)  # type: ignore[attr-defined]
            raise AttributeError(f"Codec {cls} has neither 'apersist' nor 'persist'")

        # One DB transaction for the whole batch
        saved = []
        with transaction.atomic():
            for it in items:
                res = await _persist_one(it)
                saved.append(res)
        return saved

    def persist_batch(self, items: Iterable[Any], *, ctx: dict | None = None) -> list[Any]:
        """Sync adapter for `apersists_batch` using `async_to_sync`."""
        return async_to_sync(self.apersists_batch)(items, ctx=ctx)


# Singleton instance for Django layer
codecs = CodecRegistry()

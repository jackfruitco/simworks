# simcore_ai_django/codecs/registry.py
from __future__ import annotations

from simcore_ai_django.codecs import DjangoBaseLLMCodec

"""
Django codec class registry (identity-first, async batch helpers).

Differences from core:
- Stores **codec classes** (not instances) keyed by the canonical identity tuple3.
- Batch helpers (`apersists_batch` / `persist_batch`) resolve a class, instantiate it,
  then call `apersist(...)` or `persist(...)` on each item.

Identity handling:
- All parsing/validation/coercion delegates to `Identity.get_for` / `.coerce_key`.
- Internal key is the normalized tuple3; external API accepts IdentityKey
  (tuple3 | dot-string | Identity).

Collision policy (aligned with core):
- `register(..., replace=False)`: strict + idempotent.
  * same class + same identity → no-op
  * different class + same identity → raise `CodecDuplicateRegistrationError`
- `register(..., replace=True)`: overwrite existing.

Public API:
    CodecRegistry.register(cls, *, replace=False) -> None
    CodecRegistry.get(identity: IdentityKey) -> type[BaseLLMCodec]
    CodecRegistry.require(identity: IdentityKey) -> type[BaseLLMCodec]
    CodecRegistry.has(identity: IdentityKey) -> bool
    CodecRegistry.all() -> tuple[type[BaseLLMCodec], ...]
    CodecRegistry.identities() -> tuple[tuple[str,str,str], ...]
    CodecRegistry.clear() -> None

Batch helpers:
    apersists_batch(items, *, ctx=None) -> list[Any]
    persist_batch(items, *, ctx=None) -> list[Any]
"""

import logging
import threading
from typing import Any, Iterable, Optional

from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction

from simcore_ai.identity import Identity, IdentityKey
from simcore_ai.codecs.base import BaseLLMCodec
from simcore_ai.codecs.exceptions import (
    CodecNotFoundError,
    CodecDuplicateRegistrationError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CodecRegistry",
    "codecs",
]


class CodecRegistry:
    """Registry of codec **classes** keyed by canonical identity tuple3."""

    _store: dict[tuple[str, str, str], type[BaseLLMCodec] | type[DjangoBaseLLMCodec]] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration (public) → strict + idempotent
    # ------------------------------------------------------------------
    @classmethod
    def register(
        cls,
        candidate: type[BaseLLMCodec],
        *,
        replace: bool = False,
    ) -> None:
        """
        Register a codec **class**.

        The class must expose a resolvable `identity` (via IdentityMixin/decorator).
        Registration is strict and idempotent; `replace=True` overwrites conflicts.
        Otherwise, a different class on the same identity raises CodecDuplicateRegistrationError.
        """
        cls._register(candidate, replace=replace)

    # ------------------------------------------------------------------
    # Registration (private write path)
    # ------------------------------------------------------------------
    @classmethod
    def _register(cls, candidate: type[BaseLLMCodec], *, replace: bool = False) -> None:
        with cls._lock:
            ident_obj = getattr(candidate, "identity", None)
            if ident_obj is None or not isinstance(ident_obj, Identity):
                raise TypeError(
                    f"{candidate.__name__} is missing `identity: Identity` "
                    "(ensure IdentityMixin/decorator stamped it before registration)"
                )
            ident_key = ident_obj.as_tuple3

            existing = cls._store.get(ident_key)
            if existing is None:
                cls._store[ident_key] = candidate
            elif existing is candidate:
                # idempotent re-registration (e.g., autoreload)
                return
            else:
                if replace:
                    logger.info("codec.register.replace %s", ident_obj.as_str)
                    cls._store[ident_key] = candidate
                else:
                    raise CodecDuplicateRegistrationError(
                        f"Codec identity already registered to {existing!r}: {ident_obj.as_str}"
                    )

        logger.info("codec.registered %s (class=%s)", ident_obj.as_str, candidate.__name__)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    @classmethod
    def has(cls, identity: IdentityKey) -> bool:
        ident = Identity.coerce_key(identity).as_tuple3
        return ident in cls._store

    @classmethod
    def get(cls, identity: IdentityKey) -> type[BaseLLMCodec]:
        ident = Identity.coerce_key(identity).as_tuple3
        try:
            return cls._store[ident]
        except KeyError:
            logger.warning("codec.lookup.miss %s", ".".join(ident))
            raise CodecNotFoundError(f"No codec registered at '{'.'.join(ident)}'")

    @classmethod
    def require(cls, identity: IdentityKey) -> type[BaseLLMCodec]:
        return cls.get(identity)

    @classmethod
    def all(cls) -> tuple[type[BaseLLMCodec], ...]:
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def identities(cls) -> tuple[tuple[str, str, str], ...]:
        with cls._lock:
            return tuple(cls._store.keys())

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            logger.debug("codec.registry.clear count=%d", len(cls._store))
            cls._store.clear()

    # ------------------------------------------------------------------
    # Batch persistence (async-first)
    # ------------------------------------------------------------------
    @staticmethod
    def _identity_tuple_from_item(it: Any) -> tuple[str, str, str]:
        """
        Extract a tuple3 identity from an arbitrary item.

        Accepts:
          - item.identity: Identity → tuple3
          - item.identity: tuple[str,str,str]
          - item.identity_tuple(): -> tuple[str,str,str]
          - item.identity_as_tuple3(): -> tuple[str,str,str]
        """
        ident: Identity = getattr(it, "identity", None)
        t: tuple[str, str, str]

        if isinstance(ident, Identity):
            return ident.as_tuple3
        if isinstance(ident, tuple) and len(ident) == 3 and all(isinstance(x, str) for x in ident):
            return ident  # type: ignore[return-value]
        if callable(getattr(it, "identity_tuple", None)):
            t = it.identity_tuple()  # type: ignore[attr-defined]
            if isinstance(t, tuple) and len(t) == 3 and all(isinstance(x, str) for x in t):
                return t
        if callable(getattr(it, "identity_as_tuple3", None)):
            t = it.identity_as_tuple3()  # type: ignore[attr-defined]
            if isinstance(t, tuple) and len(t) == 3 and all(isinstance(x, str) for x in t):
                return t
        raise TypeError(f"Item {it!r} does not expose an identity tuple")

    async def apersists_batch(self, items: Iterable[Any], *, ctx: Optional[dict] = None) -> list[Any]:
        """
        Persist a batch of items in a single transaction (call-order semantics).

        For each item:
          - derive tuple3 identity via `_identity_tuple_from_item`
          - resolve registered codec class and instantiate it
          - prefer `apersist(item, ctx=...)`; otherwise call `persist(item, ctx=...)` via `sync_to_async`
        """
        ctx = ctx or {}

        async def _persist_one(it: Any) -> Any:
            key = self._identity_tuple_from_item(it)
            cls = self.get(key)  # raises CodecNotFoundError if missing
            codec = cls()  # instantiate class for this item
            if hasattr(codec, "apersist") and callable(codec.apersist):  # type: ignore[attr-defined]
                return await codec.apersist(it, ctx=ctx)  # type: ignore[attr-defined]
            if hasattr(codec, "persist") and callable(codec.persist):  # type: ignore[attr-defined]
                return await sync_to_async(codec.persist, thread_sensitive=True)(it, ctx=ctx)  # type: ignore[attr-defined]
            raise AttributeError(f"Codec {cls} has neither 'apersist' nor 'persist'")

        saved: list[Any] = []
        with transaction.atomic():
            for it in items:
                res = await _persist_one(it)
                saved.append(res)
        return saved

    def persist_batch(self, items: Iterable[Any], *, ctx: Optional[dict] = None) -> list[Any]:
        """Sync adapter for `apersists_batch`."""
        return async_to_sync(self.apersists_batch)(items, ctx=ctx)


# Singleton instance (Django-layer)
codecs = CodecRegistry()
# simcore_ai/codecs/registry.py
"""
Codec registry (core, framework-agnostic).

Identity centralization (v3)
----------------------------
- All identity handling is via `Identity.get_for` / `Identity.coerce_key`.
- Internal storage key is `identity.as_str` ("namespace.kind.name").
- Public API uses `IdentityKey` (tuple3 | dot-string | Identity) for lookups.

Storage model
-------------
- Internally we use a single flat string key: `identity.as_str`.

Collision policy
----------------
- If `replace=True`: overwrite.
- If `replace=False` and an entry exists:
    - Idempotent if the exact same instance is re-registered.
    - Otherwise **raise DuplicateIdentityError**. Use `replace=True` to explicitly overwrite.

Public API
----------
    CodecRegistry.register(codec, *, replace=False) -> None
    CodecRegistry.get(identity: IdentityKey) -> BaseLLMCodec
    CodecRegistry.require(identity: IdentityKey) -> BaseLLMCodec (raises CodecNotFoundError)
    CodecRegistry.get_default_for_bucket(identity: IdentityKey) -> BaseLLMCodec | None
    CodecRegistry.has(identity: IdentityKey) -> bool
    CodecRegistry.list() -> dict[str, BaseLLMCodec]
    CodecRegistry.clear() -> None

Top-level helpers:
    register(namespace, kind, name, codec, *, replace=False) -> None
    get_codec(identity: IdentityKey) -> Optional[BaseLLMCodec]
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from simcore_ai.identity import Identity, IdentityKey
from .base import BaseLLMCodec
from .exceptions import CodecNotFoundError, CodecDuplicateRegistrationError

logger = logging.getLogger(__name__)

__all__ = ["CodecRegistry", "get_codec"]


# ---------------------------- registry ----------------------------

class CodecRegistry:
    """Lightweight, framework-agnostic registry for LLM codecs (v3 identity)."""

    _store: Dict[tuple[str, str, str], BaseLLMCodec] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration (public) → strict + idempotent
    # ------------------------------------------------------------------
    @classmethod
    def register(
            cls,
            candidate: BaseLLMCodec,
            *,
            replace: bool = False,
    ) -> None:
        """
        Register a codec instance.

        The codec must have a resolvable `identity` (via mixin/decorator).
        Registration is strict and idempotent; `replace` overwrites conflicts.
        If a different instance is registered under the same identity and `replace` is False, a `DuplicateIdentityError` is raised.
        """
        cls._register(candidate, replace=replace)

    # ------------------------------------------------------------------
    # Registration (private write path)
    # ------------------------------------------------------------------
    @classmethod
    def _register(cls, candidate: BaseLLMCodec, *, replace: bool = False) -> None:
        with cls._lock:
            identity_ = getattr(candidate, "identity", None)
            if identity_ is None:
                raise TypeError(f"{type(candidate).__name__} is missing `identity` (use IdentityMixin/decorator)")
            ident_key: tuple[str,str,str] = identity_.as_tuple3

            existing = cls._store.get(ident_key)

            if existing is None:
                cls._store[ident_key] = candidate
            elif existing is candidate:
                # idempotent re-registration: no-op
                pass
            else:
                if replace:
                    logger.info("codec.register.replace %s", identity_.as_str)
                    cls._store[ident_key] = candidate
                else:
                    # strict collision policy: do not overwrite silently
                    raise CodecDuplicateRegistrationError(
                        f"Codec identity already registered to {existing!r}: {identity_.as_str}"
                    )

        logger.info("codec.registered %r (identity=%s)", candidate, identity_.as_str)

    # ---------------- lookups ----------------
    @classmethod
    def has(cls, identity: IdentityKey) -> bool:
        """Compatibility helper: test presence by identity."""
        ident = Identity.coerce_key(identity)
        return ident in cls._store

    @classmethod
    def get(cls, identity: IdentityKey) -> BaseLLMCodec:
        """
        Lookup a codec by IdentityKey (tuple3 | dot-string | Identity).
        Raises RegistryLookupError on miss.
        """
        ident_key = Identity.coerce_key(identity).as_str
        try:
            return cls._store[ident_key]
        except KeyError:
            logger.warning("codec.lookup.miss %s", ident_key)
            raise CodecNotFoundError(f"No codec registered at '{ident_key}'")

    @classmethod
    def require(cls, identity: IdentityKey) -> BaseLLMCodec:
        """Like get(), but raises CodecNotFoundError for convenience."""
        return cls.get(identity)

    @classmethod
    def get_default_for_bucket(cls, identity: IdentityKey) -> Optional[BaseLLMCodec]:
        """
        Return the 'default' codec for (namespace, kind), or None.
        """
        ns, kd, _ = Identity.coerce_key(identity).as_tuple3
        return cls._store.get(f"{ns}.{kd}.default")

    @classmethod
    def list(cls) -> Dict[str, BaseLLMCodec]:
        """Return a shallow copy of the registry map (keys are 'namespace.kind:name')."""
        return dict(cls._store)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered codecs (useful for tests and autoreload)."""
        logger.debug("codec.registry.clear count=%d", len(cls._store))
        cls._store.clear()


# ---------------------- top-level helpers ----------------------
def get_codec(identity: IdentityKey) -> Optional[BaseLLMCodec]:
    """
    SAFE lookup used by services:
        get_codec(namespace, "kind:name") -> codec | None
        get_codec(namespace, "default")   -> codec | None
    """
    try:
        return CodecRegistry.get(identity)
    except CodecNotFoundError:
        return None

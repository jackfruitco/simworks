# simcore_ai/codecs/registry.py
from __future__ import annotations

"""
Codec registry (core, framework-agnostic).

Stores codec *instances* keyed by their canonical identity:

    key := f"{origin}.{bucket}.{name or 'default'}".lower()

Legacy formats are removed. Codecs must expose:
    - origin: str
    - bucket: str
    - name:   str (optional; defaults to "default")

Collision policy:
    - Uses core resolve_collision (env-driven via SIMCORE_AI_DEBUG if debug flag is unset):
      * DEBUG=True → raise on duplicate
      * DEBUG=False → warn and suffix name with '-2', '-3', ...

Public API:
    CodecRegistry.register(codec, *, replace=False) -> None
    CodecRegistry.get(origin, bucket, name="default") -> BaseLLMCodec
    CodecRegistry.get_by_key(key: str) -> BaseLLMCodec
    CodecRegistry.get_default_for_bucket(origin, bucket) -> BaseLLMCodec | None
    CodecRegistry.has(origin, bucket, name="default") -> bool
    CodecRegistry.list() -> dict[str, BaseLLMCodec]
    CodecRegistry.clear() -> None

Helpers:
    register(origin, bucket, name, codec, *, replace=False) -> None
    get_codec(origin, bucket, name="default") -> Optional[BaseLLMCodec]
"""

import logging
from typing import Dict, Optional

from simcore_ai.identity.utils import resolve_collision

from .base import BaseLLMCodec
from .exceptions import CodecNotFoundError
from ..exceptions.registry_exceptions import RegistryLookupError

logger = logging.getLogger(__name__)

__all__ = ["CodecRegistry", "register", "get_codec"]


def _norm(s: Optional[str]) -> str:
    """Normalize identity parts to a consistent key-friendly form."""
    if not s:
        return ""
    return s.strip().lower().replace(" ", "_")


def _key(origin: str, bucket: str, name: Optional[str]) -> str:
    """Build the canonical registry key."""
    o = _norm(origin) or "default"
    b = _norm(bucket) or "default"
    n = _norm(name or "default") or "default"

    # Guard a few obviously bad characters for safety.
    if any(c in ("/", "\\") for c in (o + b + n)):
        raise ValueError("codec identity parts must not contain slashes")

    return f"{o}.{b}.{n}"


class CodecRegistry:
    """Lightweight, framework-agnostic registry for LLM codecs (v3 identity)."""

    _items: Dict[str, BaseLLMCodec] = {}

    @classmethod
    def has(cls, origin: str, bucket: str, name: str = "default") -> bool:
        """Return True if a codec is already registered at (origin, bucket, name)."""
        return _key(origin, bucket, name) in cls._items

    @classmethod
    def register(cls, codec: BaseLLMCodec, *, replace: bool = False) -> None:
        """
        Register a codec instance using its (origin, bucket, name) identity.

        Collision policy:
            - If replace=True and a different codec exists at the key, it will be replaced.
            - If replace=False and a different codec exists:
                • In debug → raise
                • In non-debug → suffix `name` with '-2', '-3', … until unique, then register.
            - Collisions are handled via resolve_collision.

        Raises:
            TypeError: if required attributes are missing.
        """
        origin = getattr(codec, "origin", None)
        bucket = getattr(codec, "bucket", None)
        name = getattr(codec, "name", None)  # optional; defaults to "default"

        if not origin or not isinstance(origin, str):
            raise TypeError(f"Codec {type(codec).__name__} missing required field 'origin'")
        if not bucket or not isinstance(bucket, str):
            raise TypeError(f"Codec {type(codec).__name__} missing required field 'bucket'")

        # Collision handling (only when replace=False and different object exists)
        initial_key = _key(origin, bucket, name)
        if not replace and initial_key in cls._items and cls._items[initial_key] is not codec:
            # Let the core resolver decide raise vs suffix; it operates on tuple then we rebuild key.
            def _exists(t: tuple[str, str, str]) -> bool:
                return _key(*t) in cls._items

            o = _norm(origin) or "default"
            b = _norm(bucket) or "default"
            n = _norm(name or "default") or "default"
            o, b, n = resolve_collision("codec", (o, b, n), exists=_exists)
            # Update the codec's own identity to the resolved value so downstream users see the final name.
            setattr(codec, "origin", o)
            setattr(codec, "bucket", b)
            setattr(codec, "name", n)

        k = _key(getattr(codec, "origin", origin), getattr(codec, "bucket", bucket), getattr(codec, "name", name))

        # If replace=True or unique key → register.
        cls._items[k] = codec
        logger.info("codec.registered %s", k)

    @classmethod
    def get(cls, origin: str, bucket: str, name: str = "default") -> BaseLLMCodec:
        """
        Lookup a codec by identity parts. Returns the codec or raises on miss.

        Raises:
            RegistryLookupError: when no codec is registered at the key.
        """
        k = _key(origin, bucket, name)
        try:
            return cls._items[k]
        except KeyError:
            logger.warning("codec.lookup.miss %s", k)
            raise RegistryLookupError(f"No codec registered at '{k}'")

    @classmethod
    def get_by_key(cls, key: str) -> BaseLLMCodec:
        """
        Lookup a codec by canonical key "origin.bucket.name".
        """
        k = _norm(key)
        try:
            return cls._items[k]
        except KeyError:
            logger.warning("codec.lookup_by_key.miss %s", k)
            raise RegistryLookupError(f"No codec registered at '{k}'")

    @classmethod
    def get_default_for_bucket(cls, origin: str, bucket: str) -> Optional[BaseLLMCodec]:
        """
        Convenience: return the 'default' codec for a given (origin, bucket), or None.
        """
        k = _key(origin, bucket, "default")
        return cls._items.get(k)

    @classmethod
    def require(cls, origin: str, bucket: str, name: str = "default") -> BaseLLMCodec:
        """
        Like get(), but raises CodecNotFoundError instead of RegistryLookupError.
        """
        try:
            return cls.get(origin, bucket, name)
        except RegistryLookupError as exc:
            raise CodecNotFoundError(str(exc)) from exc

    @classmethod
    def list(cls) -> Dict[str, BaseLLMCodec]:
        """Return a shallow copy of the registry map."""
        return dict(cls._items)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered codecs (useful for tests and autoreload)."""
        logger.debug("codec.registry.clear count=%d", len(cls._items))
        cls._items.clear()


# Optional top-level helpers for manual registration / lookups
def register(origin: str, bucket: str, name: str, codec: BaseLLMCodec, *, replace: bool = False) -> None:
    """
    Manually register a codec instance when not using the @codec decorator.
    Applies collision policy if replace=False.
    """
    # Set identity attributes on the instance when provided externally.
    codec.origin = origin  # type: ignore[attr-defined]
    codec.bucket = bucket  # type: ignore[attr-defined]
    codec.name = name  # type: ignore[attr-defined]
    CodecRegistry.register(codec, replace=replace)


def get_codec(origin: str, bucket: str, name: str = "default") -> Optional[BaseLLMCodec]:
    """
    Safe lookup helper; returns None on miss.
    """
    try:
        return CodecRegistry.get(origin, bucket, name)
    except RegistryLookupError:
        return None

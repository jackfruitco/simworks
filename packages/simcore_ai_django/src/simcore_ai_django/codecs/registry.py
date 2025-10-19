from __future__ import annotations

"""
Django codec registry.

Stores codec **classes** keyed by tuple identity (origin, bucket, name).
Canonical string form is "origin.bucket.name" (dot-only). No legacy formats.

Collision policy:
  - Uses Django-aware resolver:
      * settings.DEBUG=True → raise
      * settings.DEBUG=False → warn and suffix the **name** with '-2', '-3', …

Public API:
    DjangoCodecRegistry.register(origin, bucket, name, codec_class) -> None
    DjangoCodecRegistry.get_codec(origin, bucket, name) -> Type[DjangoBaseLLMCodec] | None
    DjangoCodecRegistry.require(origin, bucket, name) -> Type[DjangoBaseLLMCodec]
    DjangoCodecRegistry.has(origin, bucket, name) -> bool
    DjangoCodecRegistry.names() -> Iterable[str]
    DjangoCodecRegistry.clear() -> None
    register(origin, bucket, name, codec_class) -> None
    get_codec(origin, bucket, name) -> Optional[Type[DjangoBaseLLMCodec]]

Legacy helpers and namespace/colon forms have been removed.
"""

import logging
from typing import Dict, Iterable, Optional, Tuple, Type

from simcore_ai_django.identity import resolve_collision_django
from .base import DjangoBaseLLMCodec

logger = logging.getLogger(__name__)

__all__ = ["DjangoCodecRegistry", "register", "get_codec"]


# ------------------------ helpers ------------------------

def _norm(val: Optional[str]) -> str:
    s = "" if val is None else str(val).strip().lower().replace(" ", "_")
    return s or "default"


# ------------------------ registry ------------------------

class DjangoCodecRegistry:
    """
    Registry of Django codec **classes** keyed by tuple identity: (origin, bucket, name).
    """

    _by_tuple: Dict[Tuple[str, str, str], Type[DjangoBaseLLMCodec]] = {}

    @classmethod
    def has(cls, origin: str, bucket: str, name: str) -> bool:
        """Return True if a codec class is already registered at the tuple identity."""
        key = (_norm(origin), _norm(bucket), _norm(name))
        return key in cls._by_tuple

    @classmethod
    def register(cls, origin: str, bucket: str, name: str, codec_class: Type[DjangoBaseLLMCodec]) -> None:
        """
        Register a codec class by (origin, bucket, name), applying collision policy.
        """
        ns = _norm(origin)
        buck = _norm(bucket)
        nm = _norm(name)

        key = (ns, buck, nm)
        if key in cls._by_tuple and cls._by_tuple[key] is not codec_class:
            # Resolve collision via Django-aware policy (DEBUG vs prod).
            def _exists(t: Tuple[str, str, str]) -> bool:
                return t in cls._by_tuple

            ns, buck, nm = resolve_collision_django("codec", (ns, buck, nm), exists=_exists)
            key = (ns, buck, nm)

        # annotate class with identity (helpful for logging/inspection)
        setattr(codec_class, "origin", ns)
        setattr(codec_class, "bucket", buck)
        setattr(codec_class, "name", nm)

        cls._by_tuple[key] = codec_class
        logger.info("django.codec.registered %s", ".".join(key))

    @classmethod
    def get_codec(cls, origin: str, bucket: str, name: str) -> Optional[Type[DjangoBaseLLMCodec]]:
        """
        Return a codec class for (origin, bucket, name) if registered, with fallbacks:
          - (origin, bucket, "default")
          - (origin, "default", "default")
        """
        ns = _norm(origin)
        buck = _norm(bucket)
        nm = _norm(name)

        # Exact
        obj = cls._by_tuple.get((ns, buck, nm))
        if obj:
            return obj

        # Fallbacks
        obj = cls._by_tuple.get((ns, buck, "default"))
        if obj:
            return obj
        obj = cls._by_tuple.get((ns, "default", "default"))
        if obj:
            return obj

        return None

    @classmethod
    def require(cls, origin: str, bucket: str, name: str) -> Type[DjangoBaseLLMCodec]:
        obj = cls.get_codec(origin, bucket, name)
        if obj is None:
            available = ", ".join(sorted(f"{ns}.{b}.{n}" for (ns, b, n) in cls._by_tuple.keys())) or "<none>"
            raise LookupError(f"Codec '{origin}.{bucket}.{name}' not registered; available: {available}")
        return obj

    @classmethod
    def clear(cls) -> None:
        """Clear all registered codec classes (useful in tests and autoreload)."""
        cls._by_tuple.clear()

    @classmethod
    def names(cls) -> Iterable[str]:
        """Iterate canonical codec identities ("origin.bucket.name")."""
        return (f"{ns}.{b}.{n}" for (ns, b, n) in cls._by_tuple.keys())


# ------------------------ API helpers ------------------------

def register(origin: str, bucket: str, name: str, codec_class: Type[DjangoBaseLLMCodec]) -> None:
    """
    Manual registration helper mirroring the class method.
    """
    DjangoCodecRegistry.register(origin, bucket, name, codec_class)


def get_codec(origin: str, bucket: str, name: str) -> Optional[Type[DjangoBaseLLMCodec]]:
    """
    Safe lookup; returns None on miss.
    """
    return DjangoCodecRegistry.get_codec(origin, bucket, name)
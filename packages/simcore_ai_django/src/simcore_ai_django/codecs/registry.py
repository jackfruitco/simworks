from __future__ import annotations

"""
Django codec registry (classes only).

Stores codec **classes** keyed by tuple identity (origin, bucket, name).
Canonical string form is "origin.bucket.name".

Collision policy:
  - Enforce tuple³ uniqueness and RAISE DuplicateCodecIdentityError.
  - Decorators are responsible for suffixing ('-2', '-3', ...) and retrying.

Public API:
    DjangoCodecRegistry.register(origin, bucket, name, codec_class) -> None
    DjangoCodecRegistry.get_codec(origin, bucket, name) -> type[DjangoBaseLLMCodec] | None
    DjangoCodecRegistry.require(origin, bucket, name) -> type[DjangoBaseLLMCodec]
    DjangoCodecRegistry.has(origin, bucket, name) -> bool
    DjangoCodecRegistry.names() -> Iterable[str]
    DjangoCodecRegistry.clear() -> None
    register(origin, bucket, name, codec_class) -> None
    get_codec(origin, bucket, name) -> type[DjangoBaseLLMCodec] | None
"""

from collections.abc import Iterable
import logging
import threading
from typing import Optional, Tuple, Type

from .base import DjangoBaseLLMCodec

logger = logging.getLogger(__name__)

__all__ = ["DjangoCodecRegistry", "DuplicateCodecIdentityError", "register", "get_codec"]


class DuplicateCodecIdentityError(Exception):
    """Raised when a codec identity (origin, bucket, name) is already registered."""


def _norm(val: Optional[str]) -> str:
    s = "" if val is None else str(val).strip().lower().replace(" ", "_")
    return s or "default"


class DjangoCodecRegistry:
    """Registry of Django codec **classes** keyed by (origin, bucket, name)."""

    _by_tuple: dict[tuple[str, str, str], Type[DjangoBaseLLMCodec]] = {}
    _lock = threading.RLock()

    @classmethod
    def has(cls, origin: str, bucket: str, name: str) -> bool:
        key = (_norm(origin), _norm(bucket), _norm(name))
        with cls._lock:
            return key in cls._by_tuple

    @classmethod
    def register(cls, origin: str, bucket: str, name: str, codec_class: Type[DjangoBaseLLMCodec]) -> None:
        ns = _norm(origin)
        buck = _norm(bucket)
        nm = _norm(name)
        key = (ns, buck, nm)

        with cls._lock:
            existing = cls._by_tuple.get(key)
            if existing and existing is not codec_class:
                raise DuplicateCodecIdentityError(f"{ns}.{buck}.{nm}")

            # annotate class with identity (useful for logs/inspection)
            setattr(codec_class, "origin", ns)
            setattr(codec_class, "bucket", buck)
            setattr(codec_class, "name", nm)

            cls._by_tuple[key] = codec_class
            logger.info("django.codec.registered %s", ".".join(key))

    @classmethod
    def get_codec(cls, origin: str, bucket: str, name: str) -> Type[DjangoBaseLLMCodec] | None:
        ns = _norm(origin)
        buck = _norm(bucket)
        nm = _norm(name)

        with cls._lock:
            obj = cls._by_tuple.get((ns, buck, nm))
            if obj:
                return obj
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
            with cls._lock:
                available = ", ".join(sorted(f"{ns}.{b}.{n}" for (ns, b, n) in cls._by_tuple))
            raise LookupError(f"Codec '{origin}.{bucket}.{name}' not registered; available: {available}")
        return obj

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._by_tuple.clear()
            logger.debug("django.codec.registry.cleared")

    @classmethod
    def names(cls) -> Iterable[str]:
        with cls._lock:
            return tuple(f"{ns}.{b}.{n}" for (ns, b, n) in cls._by_tuple)


def register(origin: str, bucket: str, name: str, codec_class: Type[DjangoBaseLLMCodec]) -> None:
    DjangoCodecRegistry.register(origin, bucket, name, codec_class)


def get_codec(origin: str, bucket: str, name: str) -> Type[DjangoBaseLLMCodec] | None:
    return DjangoCodecRegistry.get_codec(origin, bucket, name)
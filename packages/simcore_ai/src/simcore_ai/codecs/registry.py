# simcore_ai/codecs/registry.py
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from .base import BaseLLMCodec
from .exceptions import (
    CodecError,
    CodecNotFoundError,
)
from ..exceptions.registry_exceptions import RegistryDuplicateError, RegistryLookupError


# Normalizer helper shared by both name and namespace
def _norm(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s.lower().replace(" ", "_") if s else None


class CodecRegistry:
    """
    Lightweight, framework-agnostic codec registry for the core package.
    Stores codec *instances* keyed by:
      - global name: 'name'
      - namespaced tuple: (namespace, name) where 'name' may be 'bucket:name'
    """
    _by_name: Dict[str, BaseLLMCodec] = {}
    _by_ns: Dict[Tuple[str, str], BaseLLMCodec] = {}

    @classmethod
    def register(cls, codec: BaseLLMCodec) -> None:
        name = getattr(codec, "name", None)
        if not name or not isinstance(name, str):
            raise CodecError("Codec must define a non-empty string 'name'")
        name_n = _norm(name)
        if not name_n:
            raise CodecError("Codec name must not be empty after normalization")

        namespace = getattr(codec, "namespace", None)
        ns_n = _norm(namespace) or "default"

        key = (ns_n, name_n)
        if key in cls._by_ns:
            # Idempotent registration (autoreload safety): ignore if same object
            if cls._by_ns[key] is codec:
                return
            raise RegistryDuplicateError(f"Duplicate codec for namespace={ns_n!r}, name={name_n!r}")

        if name_n in cls._by_name and cls._by_name[name_n] is not codec:
            raise RegistryDuplicateError(f"Duplicate codec name (global): {name}")

        cls._by_ns[key] = codec
        cls._by_name[name_n] = codec

    @classmethod
    def get(cls, name: str) -> Optional[BaseLLMCodec]:
        name_n = _norm(name)
        return cls._by_name.get(name_n) if name_n else None

    @classmethod
    def get_codec(cls, namespace: str, name: str) -> Optional[BaseLLMCodec]:
        """
        Prefer namespaced lookup, with graceful fallbacks:
          1) exact (namespace, name)
          2) (namespace, "default")
          3) global name-only
          4) global "default"
        """
        ns_n = _norm(namespace) or "default"
        name_n = _norm(name) or "default"

        # Exact
        codec = cls._by_ns.get((ns_n, name_n))
        if codec:
            return codec

        # Namespace default
        codec = cls._by_ns.get((ns_n, "default"))
        if codec:
            return codec

        # Global name fallback
        codec = cls._by_name.get(name_n)
        if codec:
            return codec

        # Global default
        return cls._by_name.get("default")

    @classmethod
    def require(cls, name: str, namespace: Optional[str] = None) -> BaseLLMCodec:
        if namespace is not None:
            codec = cls.get_codec(namespace, name)
        else:
            codec = cls.get(name)
        if codec is None:
            if namespace is not None:
                raise CodecNotFoundError(f"Codec '{name}' not registered in namespace '{namespace}'")
            else:
                raise RegistryLookupError(f"Codec '{name}' not registered")
        return codec

    @classmethod
    def names(cls) -> Iterable[str]:
        return cls._by_name.keys()

    @classmethod
    def clear(cls) -> None:
        cls._by_name.clear()
        cls._by_ns.clear()


# Top-level helpers mirroring Django layer’s surface
def register(namespace: str, name: str, codec: BaseLLMCodec) -> None:
    # Allow manual registration when not using the decorator
    codec.namespace = namespace  # type: ignore[attr-defined]
    codec.name = name  # type: ignore[attr-defined]
    CodecRegistry.register(codec)


def get_codec(namespace: str, name: str) -> Optional[BaseLLMCodec]:
    return CodecRegistry.get_codec(namespace, name)

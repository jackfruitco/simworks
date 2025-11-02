# simcore_ai/codecs/registry.py
from __future__ import annotations

"""
Codec registry (core, framework-agnostic).

Identity & storage model (v3)
-----------------------------
- Codecs expose identity via IdentityMixin:
    codec.identity.as_tuple3 -> (namespace, kind, name)
    codec.identity.as_str    -> "namespace.kind.name"
- Registry stores codecs under a **two-part** logical key:
    (namespace, key2) where key2 := "kind:name" or "default"
  Internally we use a single flat string key:
    store_key(namespace, key2) -> f"{namespace_lower}.{key2_lower}"

Why two-part?
-------------
`BaseLLMService.get_codec()` calls the core helper as:
    get_codec(namespace, key_name)
where key_name is either "kind:name" or "default".
This registry aligns to that API directly.

Collision policy
----------------
- If `replace=True`: overwrite.
- If `replace=False` and an entry exists:
    - Log a warning and **last-write-wins** (overwrite) for simplicity & stability.
    - We intentionally do **not** mutate codec identity or suffix names in the registry.
      (Suffixing would break stable lookups unless callers also know the suffix.)

Public API
----------
    CodecRegistry.register(codec, *, replace=False) -> None
    CodecRegistry.get(namespace, key2: str) -> BaseLLMCodec
    CodecRegistry.require(namespace, key2: str) -> BaseLLMCodec (CodecNotFoundError)
    CodecRegistry.get_default_for_bucket(namespace, kind) -> BaseLLMCodec | None
    CodecRegistry.get_by_key(key: str) -> BaseLLMCodec  # accepts "ns.kind.name" or "ns.kind:name"
    CodecRegistry.has(namespace, kind, name="default") -> bool  # compat helper
    CodecRegistry.list() -> dict[str, BaseLLMCodec]
    CodecRegistry.clear() -> None

Top-level helpers:
    register(namespace, kind, name, codec, *, replace=False) -> None   # sets instance hints then registers
    get_codec(namespace, key2: str) -> Optional[BaseLLMCodec]           # SAFE lookup used by services
"""

import logging
from typing import Dict, Optional, Tuple

from .base import BaseLLMCodec
from .exceptions import CodecNotFoundError
from ..exceptions.registry_exceptions import RegistryLookupError

logger = logging.getLogger(__name__)

__all__ = ["CodecRegistry", "register", "get_codec"]


# ---------------------------- helpers ----------------------------

def _norm(s: Optional[str]) -> str:
    """Normalize to a key-friendly token (lowercase, strip, spaces->underscore)."""
    if not s:
        return ""
    return str(s).strip().lower().replace(" ", "_")


def _store_key(namespace: str, key2: str) -> str:
    """
    Build the internal storage key:
        namespace.key2
    where key2 is "kind:name" or "default"
    """
    ns = _norm(namespace) or "default"
    k2 = _norm(key2) or "default"
    if any(c in ("/", "\\") for c in (ns + k2)):
        raise ValueError("codec identity parts must not contain slashes")
    return f"{ns}.{k2}"


def _to_key2(kind: Optional[str], name: Optional[str]) -> str:
    """Construct the two-part logical key ("kind:name") or 'default'."""
    k = _norm(kind)
    n = _norm(name or "default")
    if not k:
        # When kind is missing/empty, treat entire key as 'default'
        return "default"
    return f"{k}:{n}"


def _parse_any_key_str(key: str) -> Tuple[str, str]:
    """
    Accepts either:
      - 'namespace.kind.name'  -> returns (namespace, 'kind:name')
      - 'namespace.kind:name'  -> returns (namespace, 'kind:name')
    """
    raw = str(key or "").strip()
    if not raw:
        raise ValueError("empty key")
    # Prefer dot form split first
    if raw.count(".") == 2 and ":" not in raw:
        ns, kd, nm = raw.split(".", 3)
        return (_norm(ns) or "default", f"{_norm(kd) or 'default'}:{_norm(nm) or 'default'}")
    # Try dot + colon (namespace.kind:name)
    if "." in raw and ":" in raw:
        ns, rest = raw.split(".", 1)
        return (_norm(ns) or "default", _norm(rest) or "default")
    # As a last resort, treat it as a key2 and require a namespace-less lookup (unsupported here)
    raise ValueError(f"Unrecognized key format: {key!r}")


# ---------------------------- registry ----------------------------

class CodecRegistry:
    """Lightweight, framework-agnostic registry for LLM codecs (v3 identity)."""

    _items: Dict[str, BaseLLMCodec] = {}

    @classmethod
    def register(cls, codec: BaseLLMCodec, *, replace: bool = False) -> None:
        """
        Register a codec instance using its identity:
          ns, kind, name = codec.identity.as_tuple3 (preferred)
          or fall back to codec.namespace/kind/name (legacy).

        Collision policy:
          - replace=True  -> overwrite silently
          - replace=False -> warn, last-write-wins overwrite
        """
        # Prefer unified identity; fall back to legacy attributes if necessary
        ns = kd = nm = None
        ident = getattr(codec, "identity", None)
        if ident is not None and hasattr(ident, "as_tuple3"):
            try:
                ns, kd, nm = ident.as_tuple3  # type: ignore[attr-defined]
            except Exception:
                ns = kd = nm = None

        if not ns or not kd:
            # Legacy fallback
            ns = getattr(codec, "namespace", ns)
            kd = getattr(codec, "kind", kd)
            nm = getattr(codec, "name", nm)

        # Basic validation
        if not isinstance(ns, str) or not ns.strip():
            raise TypeError(f"Codec {type(codec).__name__} missing required field 'namespace'")
        if not isinstance(kd, str) or not kd.strip():
            raise TypeError(f"Codec {type(codec).__name__} missing required field 'kind'")

        key2 = _to_key2(kd, nm)
        skey = _store_key(ns, key2)

        if skey in cls._items and cls._items[skey] is not codec:
            if replace:
                logger.info("codec.register.replace %s", skey)
            else:
                logger.warning("codec.register.collision (last-write-wins) %s", skey)

        cls._items[skey] = codec
        # Friendly log with stable identity string if available
        ident_str = getattr(ident, "as_str", None) if ident is not None else None
        logger.info("codec.registered %s (identity=%s)", skey, ident_str or f"{_norm(ns)}.{_norm(kd)}.{_norm(nm or 'default')}")

    @classmethod
    def has(cls, namespace: str, kind: str, name: str = "default") -> bool:
        """Compatibility helper: test presence by (namespace, kind, name)."""
        skey = _store_key(namespace, _to_key2(kind, name))
        return skey in cls._items

    @classmethod
    def get(cls, namespace: str, key2: str) -> BaseLLMCodec:
        """
        Lookup a codec by (namespace, key2) where key2 is 'kind:name' or 'default'.
        Raises RegistryLookupError on miss.
        """
        skey = _store_key(namespace, key2)
        try:
            return cls._items[skey]
        except KeyError:
            logger.warning("codec.lookup.miss %s", skey)
            raise RegistryLookupError(f"No codec registered at '{skey}'")

    @classmethod
    def require(cls, namespace: str, key2: str) -> BaseLLMCodec:
        """Like get(), but raises CodecNotFoundError for convenience."""
        try:
            return cls.get(namespace, key2)
        except RegistryLookupError as exc:
            raise CodecNotFoundError(str(exc)) from exc

    @classmethod
    def get_by_key(cls, key: str) -> BaseLLMCodec:
        """
        Lookup by combined string:
          - 'namespace.kind.name'  (normalized to (namespace, 'kind:name'))
          - 'namespace.kind:name'  (already (namespace, key2))
        """
        ns, key2 = _parse_any_key_str(key)
        return cls.get(ns, key2)

    @classmethod
    def get_default_for_bucket(cls, namespace: str, kind: str) -> Optional[BaseLLMCodec]:
        """
        Return the 'default' codec for (namespace, kind), or None.
        """
        skey = _store_key(namespace, _to_key2(kind, "default"))
        return cls._items.get(skey)

    @classmethod
    def list(cls) -> Dict[str, BaseLLMCodec]:
        """Return a shallow copy of the registry map (keys are 'namespace.kind:name')."""
        return dict(cls._items)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered codecs (useful for tests and autoreload)."""
        logger.debug("codec.registry.clear count=%d", len(cls._items))
        cls._items.clear()


# ---------------------- top-level helpers ----------------------

def register(namespace: str, kind: str, name: str, codec: BaseLLMCodec, *, replace: bool = False) -> None:
    """
    Manual registration helper (e.g., when not using decorators).

    We do not mutate the codec's internal identity; we attach hints to aid the
    resolver/fallback and then delegate to the registry.
    """
    # Attach hints for legacy fallbacks if necessary
    setattr(codec, "namespace", namespace)
    setattr(codec, "kind", kind)
    setattr(codec, "name", name)
    CodecRegistry.register(codec, replace=replace)


def get_codec(namespace: str, key2: str) -> Optional[BaseLLMCodec]:
    """
    SAFE lookup used by services:
        get_codec(namespace, "kind:name") -> codec | None
        get_codec(namespace, "default")   -> codec | None
    """
    try:
        return CodecRegistry.get(namespace, key2)
    except RegistryLookupError:
        return None
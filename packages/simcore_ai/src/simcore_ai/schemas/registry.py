# simcore_ai/schemas/registry.py
"""
Response schema registry (AIv3 / Identity-first).

- Stores **response schema classes** keyed by canonical identity tuple (namespace, kind, name).
- Requires classes to expose an `identity` (Identity object). For transitional compatibility,
  if a class lacks `identity` but exposes string attrs `namespace/kind/name`, we coerce them
  to an Identity (and stamp it back on the class) once at registration time.

Public API mirrors other registries (prompt, codec):
    ResponseSchemaRegistry.register(cls)
    ResponseSchemaRegistry.get(tuple3) / .get_str("ns.kind.name")
    ResponseSchemaRegistry.require(tuple3) / .require_str("ns.kind.name")
    ResponseSchemaRegistry.all()        # returns a tuple of classes
    ResponseSchemaRegistry.identities() # returns a tuple of tuple3 keys
    ResponseSchemaRegistry.clear()

Decorators:
    @register_response_schema
    def class ...

    @response_schema(namespace="...", kind="...", name="...")
    def class ...

Notes:
- Keys are stored internally as tuple3 to avoid accidental string canonicalization bugs.
- Logging is conservative; tracing (if desired) should be done by callers at definition time.
"""

from __future__ import annotations

import logging
import threading
from typing import ClassVar

from simcore_ai.identity.base import Identity

_logger = logging.getLogger(__name__)


# -------------------- Errors --------------------

class DuplicateResponseSchemaIdentityError(Exception):
    """Raised when a duplicate identity key is registered with a different schema class."""


class ResponseSchemaNotFoundError(KeyError):
    """Raised when a response schema is not found in the registry."""


# -------------------- Registry --------------------

class ResponseSchemaRegistry:
    """Global registry for response schema **classes** keyed by (namespace, kind, name)."""

    _store: dict[tuple[str, str, str], type] = {}
    _lock: ClassVar[threading.RLock] = threading.RLock()

    # ---- registration ----
    @classmethod
    def register(cls, schema_cls: type) -> None:
        """
        Register a schema class under its canonical identity.

        The class must have an `identity: Identity`. For transitional compatibility,
        if `identity` is missing but `namespace/kind/name` string attributes exist,
        they will be coerced to an Identity and stamped onto the class.
        """
        ident = cls._identity_for_cls(schema_cls)  # may stamp schema_cls.identity
        key = ident.as_tuple3
        with cls._lock:
            existing = cls._store.get(key)
            if existing is None:
                cls._store[key] = schema_cls
                _logger.info("Registered response schema %s as %s", schema_cls.__name__, ident.as_str)
                return
            if existing is schema_cls:
                # idempotent
                return
            raise DuplicateResponseSchemaIdentityError(
                f"Identity already registered by a different class: {ident.as_str} -> {existing!r} vs {schema_cls!r}"
            )

    # ---- lookup ----
    @classmethod
    def get(cls, key: tuple[str, str, str]) -> type | None:
        with cls._lock:
            return cls._store.get(key)

    @classmethod
    def require(cls, key: tuple[str, str, str]) -> type:
        out = cls.get(key)
        if out is None:
            raise ResponseSchemaNotFoundError("Schema not found for key: %s" % (".".join(key)))
        return out

    @classmethod
    def get_str(cls, dot: str) -> type | None:
        try:
            ident = Identity.from_string(dot)
        except Exception:
            return None
        return cls.get(ident.as_tuple3)

    @classmethod
    def require_str(cls, dot: str) -> type:
        ident = Identity.from_string(dot)
        return cls.require(ident.as_tuple3)

    # ---- thin backward-compat helpers (namespace/kind/name) ----
    @classmethod
    def has(cls, namespace: str, kind: str, name: str = "default") -> bool:
        with cls._lock:
            return (namespace, kind, name) in cls._store

    @classmethod
    def get_legacy(cls, namespace: str, kind: str, name: str = "default") -> type | None:
        return cls.get((namespace, kind, name))

    @classmethod
    def require_legacy(cls, namespace: str, kind: str, name: str = "default") -> type:
        return cls.require((namespace, kind, name))

    # ---- introspection ----
    @classmethod
    def all(cls) -> tuple[type, ...]:
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def identities(cls) -> tuple[tuple[str, str, str], ...]:
        with cls._lock:
            return tuple(cls._store.keys())

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._store.clear()
            _logger.debug("Cleared all response schemas from registry")

    # ---- internals ----
    @classmethod
    def _identity_for_cls(cls, schema_cls: type) -> Identity:
        """
        Resolve/validate the class identity.
        Preferred: class exposes `identity: Identity` (via IdentityMixin or decorator).
        Transitional: accept legacy string attrs (`namespace/kind/name`) and coerce.
        """
        # Preferred path
        ident = getattr(schema_cls, "identity", None)
        if isinstance(ident, Identity):
            return ident

        # Transitional fallback: legacy attrs → Identity, then stamp back
        ns = getattr(schema_cls, "namespace", None)
        kd = getattr(schema_cls, "kind", None)
        nm = getattr(schema_cls, "name", None)
        if all(isinstance(x, str) and x for x in (ns, kd, nm)):
            coerced = Identity.from_parts(namespace=ns, kind=kd, name=nm)
            try:
                # If class uses IdentityMixin with a setter, this will normalize.
                setattr(schema_cls, "identity", coerced)
            except Exception:
                # Best effort: not fatal if class blocks attribute set; registry still uses coerced
                pass
            return coerced

        raise TypeError(
            f"{schema_cls.__name__} must define an `identity: Identity` or legacy string attrs "
            f"`namespace/kind/name` for transitional compatibility."
        )


__all__ = [
    "ResponseSchemaRegistry",
    "DuplicateResponseSchemaIdentityError",
    "ResponseSchemaNotFoundError",
]

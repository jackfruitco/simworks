# simcore_ai/promptkit/registry.py
from __future__ import annotations

from .exceptions import DuplicatePromptSectionIdentityError, PromptSectionNotFoundError
from ..identity.exceptions import IdentityValidationError

"""
Prompt section registry (AIv3 / Identity-first).

- Stores **PromptSection classes** keyed by a tuple `(namespace, kind, name)`.
- Accepts tuple3 / Identity / canonical dot string for lookups.
- Strict + idempotent registration: same class+key is a no-op; different class on same key raises.
- All identity parsing/coercion is delegated to the core Identity package.

Typical usage:
    @register_section
    class MySection(PromptSection):
        from simcore_ai.identity import Identity
        identity = Identity(namespace="chatlab", kind="patient", name="initial")

    SectionCls = PromptRegistry.require("chatlab.patient.initial")
"""

from typing import Type
import logging
import threading

from simcore_ai.identity import coerce_identity_key, IdentityKey
from simcore_ai.tracing import service_span_sync

from .types import PromptSection

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Global registry for `PromptSection` **classes** keyed by tuple `(namespace, kind, name)`.

    We keep classes (not instances) so sections can carry behavior and schemas.
    """

    _store: dict[tuple[str, str, str], Type[PromptSection]] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration (public) → strict + idempotent
    # ------------------------------------------------------------------
    @classmethod
    def register(
            cls,
            candidate: type[PromptSection],
            *,
            replace: bool = False,
    ) -> None:
        """Register a Prompt Section instance.

        The Prompt Section must have a resolvable `identity` (via mixin/decorator).
        Registration is strict and idempotent; `replace` overwrites conflicts.
        If a different instance is registered under the same identity and `replace` is False, a `DuplicateIdentityError` is raised.
        """
        cls._register(candidate, replace=replace)

    # ------------------------------------------------------------------
    # Registration (private write path)
    # ------------------------------------------------------------------
    @classmethod
    def _register(
            cls,
            candidate: type[PromptSection],
            *,
            replace: bool = False,
    ) -> None:
        """Private single write path with dupe detection."""
        with cls._lock:
            identity_ = getattr(candidate, "identity", None)
            if identity_ is None:
                raise TypeError(f"{type(candidate).__name__} is missing `identity` (use IdentityMixin/decorator)")
            ident_key: tuple[str, str, str] = identity_.as_tuple3

            existing = cls._store.get(ident_key)

            # If not already registered, register it
            if existing is None:
                cls._store[ident_key] = candidate
                logger.info("Registered prompt section %s: %s", ident_key, candidate.__name__)
                return

            # Otherwise, if key registered, but matching class:
            #   - replace=False (default): independent registration is a no-op
            #   - replace=True: overwrite existing
            if existing is candidate:
                if replace:
                    logger.info("prompt.registry.replace %s", identity_.as_str)
                    cls._store[ident_key] = candidate
                return

            # Other, there must be a collision (raise)
            raise DuplicatePromptSectionIdentityError(identity_.as_str, existing, candidate)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, identity: IdentityKey) -> Type[PromptSection] | None:
        """Retrieve a registered `PromptSection` class by identity.

        Accepts:
          - tuple[str, str, str] (namespace, kind, name)
          - Identity (object exposing `.as_tuple3`)
          - str ("namespace.kind.name")
        """
        ident_tuple3 = coerce_identity_key(identity)
        if ident_tuple3 is None:
            logger.warning("%s could not resolve PromptSection from identity %r", cls.__name__, identity)
            return None

        ident_str = ".".join(ident_tuple3)
        with service_span_sync("ai.prompt.registry.get", attributes={"identity": ident_str}):
            with cls._lock:
                return cls._store.get(ident_tuple3)

    @classmethod
    def require(cls, identity: IdentityKey) -> Type[PromptSection]:
        """Like `get` but raises `KeyError` if not found."""
        ident_tuple3 = coerce_identity_key(identity)
        if ident_tuple3 is None:
            raise IdentityValidationError(f"Invalid identity key: {identity!r}")
        ident_str = ".".join(ident_tuple3)
        with service_span_sync("ai.prompt.registry.require", attributes={"identity": ident_str}):
            section = cls.get(ident_tuple3)
            if section is None:
                raise PromptSectionNotFoundError(f"PromptSection not registered: {ident_str}")
            return section

    # ------------------------------------------------------------------
    # Introspection / maintenance
    # ------------------------------------------------------------------
    @classmethod
    def all(cls) -> tuple[Type[PromptSection], ...]:
        """Return all registered `PromptSection` classes."""
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def identities(cls) -> tuple[tuple[str, str, str], ...]:
        """Return all registered `PromptSection` identity tuple3s."""
        with cls._lock:
            return tuple(cls._store.keys())

    @classmethod
    def clear(cls) -> None:
        """Remove all registered `PromptSection` classes."""
        with cls._lock:
            cls._store.clear()


# ----------------------------------------------------------------------
# Decorator (registration helper)
# ----------------------------------------------------------------------
def register_section(section_cls: Type[PromptSection]) -> Type[PromptSection]:
    """Decorator to register a `PromptSection` class in the global registry.

    The class must expose (or be stamped with) a class-level `identity: Identity`.
    """
    PromptRegistry.register(section_cls)
    return section_cls


__all__ = ["PromptRegistry", "register_section"]

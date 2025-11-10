from __future__ import annotations

import logging
import threading
from typing import Type, ClassVar

from simcore_ai.identity import Identity, coerce_identity_key, IdentityLike
from simcore_ai.tracing import service_span_sync
from .types import PromptSection

logger = logging.getLogger(__name__)


class DuplicatePromptSectionIdentityError(Exception):
    """Raised when a duplicate identity key is registered with a different section class."""


class PromptSectionNotFoundError(KeyError):
    """Raised when a prompt section is not found in the registry."""


class PromptSectionRegistry:
    """Global registry for `PromptSection` **classes** keyed by (namespace, kind, name)."""

    _store: dict[tuple[str, str, str], Type[PromptSection]] = {}
    _lock: ClassVar[threading.RLock] = threading.RLock()

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
        """Register a Prompt Section **class**.

        Requirements:
          • `candidate.identity` MUST be an `Identity` (stamped by decorator).
        """
        ident = getattr(candidate, "identity", None)
        if not isinstance(ident, Identity):
            raise TypeError(
                f"{getattr(candidate, '__name__', candidate)!r} must define `identity: Identity`."
            )
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
        with cls._lock:
            identity_: Identity = candidate.identity  # type: ignore[attr-defined]
            key = identity_.as_tuple3
            ident_str = identity_.as_str

            existing = cls._store.get(key)

            if existing is None:
                cls._store[key] = candidate
                logger.info("prompt.register %s -> %s", ident_str, candidate.__name__)
                return

            if existing is candidate:
                if replace:
                    logger.info("prompt.register.replace %s (same class)", ident_str)
                    cls._store[key] = candidate
                return

            if replace:
                logger.warning(
                    "prompt.register.replace.collision %s (old=%s, new=%s)",
                    ident_str, getattr(existing, "__name__", existing), candidate.__name__,
                )
                cls._store[key] = candidate
                return

            raise DuplicatePromptSectionIdentityError(
                f"PromptSection identity already registered: {ident_str} "
                f"(existing={getattr(existing, '__name__', existing)}, new={candidate.__name__})"
            )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, identity: IdentityLike) -> Type[PromptSection] | None:
        ident_tuple3 = coerce_identity_key(identity)
        if ident_tuple3 is None:
            logger.warning("%s could not resolve PromptSection from identity %r", cls.__name__, identity)
            return None

        ident_str = ".".join(ident_tuple3)
        with service_span_sync("ai.prompt.registry.get", attributes={"identity": ident_str}):
            with cls._lock:
                return cls._store.get(ident_tuple3)

    @classmethod
    def require(cls, identity: IdentityLike) -> Type[PromptSection]:
        ident_tuple3 = coerce_identity_key(identity)
        if ident_tuple3 is None:
            raise PromptSectionNotFoundError(f"Invalid identity key: {identity!r}")
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
        """
        Return all registered PromptSection classes.

        Only concrete PromptSection subclasses are returned. Legacy tuple entries
        are not supported here; callers inserting non-class values into the store
        are considered invalid.
        """
        with cls._lock:
            return tuple(
                section
                for section in cls._store.values()
                if isinstance(section, type) and issubclass(section, PromptSection)
            )

    @classmethod
    def identities(cls) -> tuple[tuple[str, str, str], ...]:
        with cls._lock:
            return tuple(cls._store.keys())

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            count = len(cls._store)
            cls._store.clear()
            logger.debug("prompt.registry.clear count=%d", count)


# Keep a legacy alias in case any import uses the old name
PromptRegistry = PromptSectionRegistry

# initialize singleton registry instance
prompts = PromptSectionRegistry()

def register_section(section_cls: Type[PromptSection]) -> Type[PromptSection]:
    """Decorator to register a `PromptSection` class in the global registry."""
    PromptSectionRegistry.register(candidate=section_cls)
    return section_cls


__all__ = [
    "PromptSectionRegistry",
    "PromptRegistry",
    "register_section",
    "DuplicatePromptSectionIdentityError",
    "PromptSectionNotFoundError",
    "prompts"
]
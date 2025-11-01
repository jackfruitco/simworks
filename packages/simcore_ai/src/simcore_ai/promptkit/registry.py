# simcore_ai/promptkit/registry.py
from __future__ import annotations

"""Prompt section registry (AIv3 / Identity-first).

- Stores **PromptSection classes** keyed by a tuple `(namespace, kind, name)`.
- Accepts **dot-only** canonical strings ("namespace.kind.name") for lookups.
- Does NOT auto-resolve or rename collisions: duplicate identities raise an error.

Typical usage:
    @register_section
    class MySection(PromptSection):
        from simcore_ai.identity import Identity
        identity = Identity.from_parts(namespace="chatlab", kind="patient", name="initial")

    SectionCls = PromptRegistry.require_str("chatlab.patient.initial")
"""

from typing import Type
from collections.abc import Iterable
import logging
import threading

from simcore_ai.identity.utils import parse_dot_identity
from simcore_ai.identity import Identity
from simcore_ai.tracing import service_span_sync

from .types import PromptSection


class DuplicatePromptSectionIdentityError(Exception):
    """Raised when a prompt section identity is already taken by a different class."""
    pass


logger = logging.getLogger(__name__)


def _identity_tuple_for_cls(section_cls: Type[PromptSection]) -> tuple[str, str, str]:
    """Derive the identity tuple (namespace, kind, name) for a section class.

    Required class-level declaration:
      • `identity: Identity` (object) — dot identities/namespace/kind/name fallbacks are no longer supported.

    Raises:
        TypeError: if `identity` is missing or not an `Identity` instance.
    """
    ident = getattr(section_cls, "identity", None)
    if isinstance(ident, Identity):
        return (ident.namespace or "default", ident.kind or "default", ident.name or section_cls.__name__)
    raise TypeError(
        f"{section_cls.__name__} must define a class-level `identity: Identity`."
    )


class PromptRegistry:
    """Global registry for `PromptSection` **classes** keyed by tuple `(namespace, kind, name)`.

    We keep classes (not instances) so sections can carry behavior and schemas.
    """

    _store: dict[tuple[str, str, str], Type[PromptSection]] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    @classmethod
    def register(
            cls,
            section_cls: type[PromptSection]
    ) -> None:
        ident_tuple = _identity_tuple_for_cls(section_cls)
        ident_str = ".".join(ident_tuple)
        with service_span_sync(
                "ai.prompt.registry.register",
                attributes={"identity": ident_str, "section_cls": section_cls.__name__},
        ):
            with cls._lock:
                if ident_tuple not in cls._store:
                    cls._store[ident_tuple] = section_cls
                    logger.info("Registered prompt section %s: %s", ident_str, section_cls.__name__)
                elif cls._store[ident_tuple] is section_cls:
                    # Already registered, no-op
                    pass
                else:
                    raise DuplicatePromptSectionIdentityError(ident_str)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, identity: tuple[str, str, str]) -> Type[PromptSection] | None:
        with cls._lock:
            return cls._store.get(identity)

    @classmethod
    def get_str(cls, key: str) -> Type[PromptSection] | None:
        """Dot-only string lookup ("namespace.kind.name")."""
        with service_span_sync("ai.prompt.registry.get_str", attributes={"identity": key}):
            ident_tuple = parse_dot_identity(key)
            return cls.get(ident_tuple)

    @classmethod
    def require(cls, identity: tuple[str, str, str]) -> Type[PromptSection]:
        ident_str = ".".join(identity)
        with service_span_sync("ai.prompt.registry.require", attributes={"identity": ident_str}):
            section = cls.get(identity)
            if section is None:
                raise KeyError(f"PromptSection not registered: {ident_str}")
            return section

    @classmethod
    def require_str(cls, key: str) -> Type[PromptSection]:
        with service_span_sync("ai.prompt.registry.require_str", attributes={"identity": key}):
            ident_tuple = parse_dot_identity(key)
            return cls.require(ident_tuple)

    # ----------------------------------------------------------------------
    # Decorator (registration helper)
    # ----------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Introspection / maintenance
    # ------------------------------------------------------------------
    @classmethod
    def all(cls) -> Iterable[Type[PromptSection]]:
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._store.clear()


# ----------------------------------------------------------------------
# Decorator (registration helper)
# ----------------------------------------------------------------------

def register_section(section_cls: Type[PromptSection]) -> Type[PromptSection]:
    """Decorator to register a `PromptSection` class in the global registry.

    The class must declare a class-level `identity: Identity`.
    """
    PromptRegistry.register(section_cls)
    return section_cls


__all__ = ["PromptRegistry", "DuplicatePromptSectionIdentityError", "register_section"]

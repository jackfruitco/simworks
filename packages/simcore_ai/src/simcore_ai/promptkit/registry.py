# simcore_ai/promptkit/registry.py
from __future__ import annotations

"""Prompt section registry (AIv3 / Identity-first).

- Stores **PromptSection classes** keyed by a tuple `(namespace, kind, name)`.
- Accepts **dot-only** canonical strings ("namespace.kind.name") for lookups.
- Does NOT auto-resolve or rename collisions: duplicate identities raise an error.

Typical usage:
    @register_section
    class MySection(PromptSection):
        namespace = "chatlab"
        kind = "patient"
        name = "initial"

    SectionCls = PromptRegistry.require_str("chatlab.patient.initial")
"""

from typing import Type
from collections.abc import Iterable
import logging
import threading

from ..identity import parse_dot_identity
from .types import PromptSection


class DuplicatePromptSectionIdentityError(Exception):
    """Raised when a prompt section identity is already taken by a different class."""
    pass


logger = logging.getLogger(__name__)


def _identity_tuple_for_cls(section_cls: Type[PromptSection]) -> tuple[str, str, str]:
    """Derives the identity tuple (namespace, kind, name) for a section class.

    Accepted class-level declarations:
      1) `identity: str` in dot-only form ("namespace.kind.name")
      2) `namespace`, `kind`, `name` class attributes (strings)

    Raises:
        TypeError: if neither form is present or invalid.
    """
    ident = getattr(section_cls, "identity", None)
    if isinstance(ident, str):
        return parse_dot_identity(ident)

    namespace = getattr(section_cls, "namespace", None)
    kind = getattr(section_cls, "kind", None)
    name = getattr(section_cls, "name", None)
    if all(isinstance(x, str) and x for x in (namespace, kind, name)):
        return (namespace, kind, name)

    raise TypeError(
        f"{section_cls.__name__} must define either `identity` as a dot string "
        f"or class attrs `namespace`, `kind`, and `name`."
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
        with cls._lock:
            if ident_tuple not in cls._store:
                cls._store[ident_tuple] = section_cls
                logger.info(
                    "Registered prompt section %s: %s",
                    ".".join(ident_tuple),
                    section_cls.__name__,
                )
            elif cls._store[ident_tuple] is section_cls:
                # Already registered, no-op
                pass
            else:
                raise DuplicatePromptSectionIdentityError(
                    f"{'.'.join(ident_tuple)}"
                )

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
        ident_tuple = parse_dot_identity(key)
        return cls.get(ident_tuple)

    @classmethod
    def require(cls, identity: tuple[str, str, str]) -> Type[PromptSection]:
        section = cls.get(identity)
        if section is None:
            raise KeyError(f"PromptSection not registered: {'.'.join(identity)}")
        return section

    @classmethod
    def require_str(cls, key: str) -> Type[PromptSection]:
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

    The class must declare either `identity` as a dot string or class attrs
    `namespace`, `kind`, and `name`.
    """
    PromptRegistry.register(section_cls)
    return section_cls


__all__ = ["PromptRegistry", "DuplicatePromptSectionIdentityError", "register_section"]

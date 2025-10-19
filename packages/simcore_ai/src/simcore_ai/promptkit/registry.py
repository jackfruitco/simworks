# simcore_ai/promptkit/registry.py
from __future__ import annotations

"""Prompt section registry (AIv3 / Identity-first).

- Stores **PromptSection classes** keyed by a tuple `(origin, bucket, name)`.
- Accepts **dot-only** canonical strings ("origin.bucket.name") for lookups.

Typical usage:
    @register_section
    class MySection(PromptSection):
        origin = "chatlab"
        bucket = "patient"
        name = "initial"

    SectionCls = PromptRegistry.require_str("chatlab.patient.initial")
"""

from typing import Iterable, Optional, Type
import logging
import threading

from ..identity import resolve_collision, parse_dot_identity
from .types import PromptSection

logger = logging.getLogger(__name__)


def _identity_tuple_for_cls(section_cls: Type[PromptSection]) -> tuple[str, str, str]:
    """Derives the identity tuple (origin, bucket, name) for a section class.

    Accepted class-level declarations:
      1) `identity: str` in dot-only form ("origin.bucket.name")
      2) `origin`, `bucket`, `name` class attributes (strings)

    Raises:
        TypeError: if neither form is present or invalid.
    """
    ident = getattr(section_cls, "identity", None)
    if isinstance(ident, str):
        return parse_dot_identity(ident)

    origin = getattr(section_cls, "origin", None)
    bucket = getattr(section_cls, "bucket", None)
    name = getattr(section_cls, "name", None)
    if all(isinstance(x, str) and x for x in (origin, bucket, name)):
        return (origin, bucket, name)

    raise TypeError(
        f"{section_cls.__name__} must define either `identity` as a dot string "
        f"or class attrs `origin`, `bucket`, and `name`."
    )


class PromptRegistry:
    """Global registry for `PromptSection` **classes** keyed by tuple `(origin, bucket, name)`.

    We keep classes (not instances) so sections can carry behavior and schemas.
    """

    _store: dict[tuple[str, str, str], Type[PromptSection]] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    @classmethod
    def register(cls, section_cls: Type[PromptSection]) -> None:
        ident_tuple = _identity_tuple_for_cls(section_cls)
        with cls._lock:
            ident_tuple = resolve_collision(
                "prompt",
                ident_tuple,
                debug=None,
                exists=lambda t: t in cls._store,
            )
            if ident_tuple in cls._store and cls._store[ident_tuple] is not section_cls:
                logger.warning(
                    "PromptRegistry overwriting existing section for %s with %s",
                    ".".join(ident_tuple),
                    section_cls.__name__,
                )
            else:
                logger.info(
                    "Registered prompt section %s: %s",
                    ".".join(ident_tuple),
                    section_cls.__name__,
                )
            cls._store[ident_tuple] = section_cls

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, identity: tuple[str, str, str]) -> Optional[Type[PromptSection]]:
        with cls._lock:
            return cls._store.get(identity)

    @classmethod
    def get_str(cls, key: str) -> Optional[Type[PromptSection]]:
        """Dot-only string lookup ("origin.bucket.name")."""
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
    `origin`, `bucket`, and `name`.
    """
    PromptRegistry.register(section_cls)
    return section_cls

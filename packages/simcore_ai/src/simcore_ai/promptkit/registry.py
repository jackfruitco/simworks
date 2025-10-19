# simcore_ai/promptkit/registry.py
from __future__ import annotations

"""Prompt section registry (AIv3 / Identity-first).

- Stores **PromptSection classes** keyed by an `Identity` (origin, bucket, name).
- Accepts **dot-only** canonical strings ("origin.bucket.name") for lookups.
- No legacy `namespace`, no colon identities.

Typical usage:
    @register_section
    class MySection(PromptSection):
        identity = Identity(origin="chatlab", bucket="patient", name="initial")

    SectionCls = PromptRegistry.require_str("chatlab.patient.initial")
"""

from typing import Iterable, Optional, Type
import logging
import threading

from simcore_ai.types.identity import Identity, parse_identity_str
from .types import PromptSection

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Global registry for `PromptSection` **classes** keyed by `Identity`.

    We keep classes (not instances) so sections can carry behavior and schemas.
    """

    _store: dict[Identity, Type[PromptSection]] = {}
    _lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    @classmethod
    def _identity_for_cls(cls, section_cls: Type[PromptSection]) -> Identity:
        """Derive an `Identity` for a section class.

        Accepted class-level declarations:
          1) `identity: Identity` (preferred)
          2) `origin`, `bucket`, `name` class attributes (strings)

        Anything else is rejected (no legacy labels or namespaces).
        """
        ident = getattr(section_cls, "identity", None)
        if isinstance(ident, Identity):
            return ident

        origin = getattr(section_cls, "origin", None)
        bucket = getattr(section_cls, "bucket", None)
        name = getattr(section_cls, "name", None)
        if all(isinstance(x, str) and x for x in (origin, bucket, name)):
            return Identity.from_parts(origin=origin, bucket=bucket, name=name)

        raise TypeError(
            f"{section_cls.__name__} must define either `identity: Identity` or class "
            f"attrs `origin`, `bucket`, and `name` (dot identity only)."
        )

    @classmethod
    def register(cls, section_cls: Type[PromptSection]) -> None:
        ident = cls._identity_for_cls(section_cls)
        with cls._lock:
            if ident in cls._store and cls._store[ident] is not section_cls:
                logger.warning(
                    "PromptRegistry overwriting existing section for %s with %s",
                    ident.to_string(),
                    section_cls.__name__,
                )
            cls._store[ident] = section_cls

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    @classmethod
    def get(cls, identity: Identity) -> Optional[Type[PromptSection]]:
        with cls._lock:
            return cls._store.get(identity)

    @classmethod
    def get_str(cls, key: str) -> Optional[Type[PromptSection]]:
        """Dot-only string lookup ("origin.bucket.name")."""
        ident = parse_identity_str(key)
        return cls.get(ident)

    @classmethod
    def require(cls, identity: Identity) -> Type[PromptSection]:
        section = cls.get(identity)
        if section is None:
            raise KeyError(f"PromptSection not registered: {identity.to_string()}")
        return section

    @classmethod
    def require_str(cls, key: str) -> Type[PromptSection]:
        ident = parse_identity_str(key)
        return cls.require(ident)

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

    The class must declare either `identity: Identity` or class attrs
    `origin`, `bucket`, and `name`.
    """
    PromptRegistry.register(section_cls)
    return section_cls
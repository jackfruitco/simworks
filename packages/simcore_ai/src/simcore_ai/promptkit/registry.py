# simcore_ai/promptkit/registry.py
from __future__ import annotations

from ..identity import Identity, coerce_identity_key

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
import logging
import threading

from simcore_ai.identity.utils import parse_dot_identity
from simcore_ai.tracing import service_span_sync

from .types import PromptSection


class DuplicatePromptSectionIdentityError(Exception):
    """Raised when a prompt section identity is already taken by a different class."""
    pass


logger = logging.getLogger(__name__)


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
        ident_obj = getattr(section_cls, "identity", None)
        if ident_obj is None or not hasattr(ident_obj, "as_tuple3") or not hasattr(ident_obj, "as_str"):
            raise TypeError(
                f"{section_cls.__name__} must expose a class-level `identity` supporting `as_tuple3` and `as_str` "
                "(e.g., via IdentityMixin or an Identity instance with those properties)."
            )
        ident_tuple = ident_obj.as_tuple3  # (namespace, kind, name)
        ident_str = ident_obj.as_str  # "namespace.kind.name"
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
    def get(cls, identity: tuple[str, str, str] | str | Identity) -> Type[PromptSection] | None:
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
    def all(cls) -> tuple[Type[PromptSection], ...]:
        """Return all registered `PromptSection` classes."""
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def identities(cls) -> tuple[tuple[str, str, str], ...]:
        """Return all registered `PromptSection` as identity tuple3's."""
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

    The class must expose a class-level `identity` that yields an `Identity`
    (e.g., via `IdentityMixin` or by assigning an `Identity` instance directly).
    """
    PromptRegistry.register(section_cls)
    return section_cls


__all__ = ["PromptRegistry", "DuplicatePromptSectionIdentityError", "register_section"]

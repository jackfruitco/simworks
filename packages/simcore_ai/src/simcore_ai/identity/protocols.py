# simcore_ai/identity/protocols.py
from __future__ import annotations

from typing import Protocol, Any, runtime_checkable, ClassVar

from .identity import Identity

__all__ = ["IdentityResolverProtocol", "IdentityProtocol"]


class IdentityResolverProtocol(Protocol):
    def resolve(self, candidate: type, **hints: Any) -> Identity: ...


@runtime_checkable
class IdentityProtocol(Protocol):
    """
    Protocol for any object (class or instance) that exposes an `identity: Identity`
    attribute or property.

    Works for:
      - Class-level access: `MyService.identity`
      - Instance-level access: `my_service.identity`
    """

    # class-level identity (e.g., via descriptor)
    identity: ClassVar[Identity]  # ensures classes are compatible
    # instance-level identity (optional)
    identity: Identity

    # Optional helpers to make type checkers happy with dynamic access
    @classmethod
    def resolve_identity(cls) -> Identity: ...

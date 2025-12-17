# orchestrai/identity/protocols.py


from typing import Protocol, Any, runtime_checkable, ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .identity import Identity

__all__ = ["IdentityResolverProtocol", "IdentityProtocol"]


class IdentityResolverProtocol(Protocol):
    def resolve(
            self,
            candidate: type,
            *,
            domain: str | None = ...,
            namespace: str | None = ...,
            group: str | None = ...,
            name: str | None = ...,
            context: dict[str, Any] | None = ...,
    ) -> "Identity": ...


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
    identity: "Identity"

    # Optional helpers to make type checkers happy with dynamic access
    @classmethod
    def resolve_identity(cls) -> "Identity": ...

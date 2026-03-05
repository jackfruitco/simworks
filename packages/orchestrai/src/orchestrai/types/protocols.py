# orchestrai/types/protocols.py
from typing import Protocol

from orchestrai.identity import Identity, IdentityLike

___all__ = ["RegistryProtocol", "ComponentProtocol", "IdentityResolverProtocol"]


class RegistryProtocol(Protocol):
    def get(self, key: IdentityLike) -> "ComponentProtocol": ...

    def register(self, key: IdentityLike, component: "ComponentProtocol") -> None: ...

    def _register(self, key: IdentityLike, component: "ComponentProtocol") -> None: ...


class ComponentProtocol(Protocol):
    identity: Identity  # every component must expose this

    def get_registry(self) -> RegistryProtocol | None: ...

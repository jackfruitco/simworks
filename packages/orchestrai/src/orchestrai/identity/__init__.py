# orchestrai/identity/__init__.py
"""Public identity API (core).

This package exposes the *dumb* Identity dataclass, the public resolver helper,
and selected low-level utilities. Identity derivation is centralized in
`orchestrai.identity.resolution.IdentityResolver`.

Exports intentionally avoid wildcard imports to keep the surface explicit.
"""


from .identity import IdentityLike, Identity
from .mixins import IdentityMixin
from .resolvers import Resolve as _Resolve, IdentityResolver, resolve_identity
from .protocols import IdentityResolverProtocol, IdentityProtocol
from .utils import DEFAULT_IDENTITY_STRIP_TOKENS, coerce_identity_key

# Ergonomic namespace without coupling the dataclass to registries:
Identity.resolve = _Resolve  # type: ignore[attr-defined]

__all__ = [
    # Types
    "Identity", "IdentityLike", "IdentityResolver",
    # Constants
    "DEFAULT_IDENTITY_STRIP_TOKENS",
    # Protocols
    "IdentityResolverProtocol", "IdentityProtocol",
    # Convenience helpers
    "coerce_identity_key",
]

# Only expose IdentityMixin if it exists locally.
if IdentityMixin is not None:  # pragma: no cover
    __all__.append("IdentityMixin")

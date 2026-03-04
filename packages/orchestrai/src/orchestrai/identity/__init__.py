# orchestrai/identity/__init__.py
"""Public identity API (core).

This package exposes the *dumb* Identity dataclass, the public resolver helper,
and selected low-level utilities. Identity derivation is centralized in
`orchestrai.identity.resolution.IdentityResolver`.

Exports intentionally avoid wildcard imports to keep the surface explicit.
"""

from .domains import (
    CODECS_DOMAIN,
    DEFAULT_DOMAIN,
    PERSIST_DOMAIN,
    PROMPT_SECTIONS_DOMAIN,
    SCHEMAS_DOMAIN,
    SERVICES_DOMAIN,
    SUPPORTED_DOMAINS,
    normalize_domain,
)
from .identity import Identity, IdentityLike
from .mixins import IdentityMixin
from .protocols import IdentityProtocol, IdentityResolverProtocol
from .resolvers import IdentityResolver, Resolve as _Resolve, resolve_identity
from .utils import DEFAULT_IDENTITY_STRIP_TOKENS, coerce_identity_key

# Ergonomic namespace without coupling the dataclass to registries:
Identity.resolve = _Resolve  # type: ignore[attr-defined]

__all__ = [
    "CODECS_DOMAIN",
    "DEFAULT_DOMAIN",
    # Constants
    "DEFAULT_IDENTITY_STRIP_TOKENS",
    "PERSIST_DOMAIN",
    "PROMPT_SECTIONS_DOMAIN",
    "SCHEMAS_DOMAIN",
    "SERVICES_DOMAIN",
    "SUPPORTED_DOMAINS",
    # Types
    "Identity",
    "IdentityLike",
    "IdentityProtocol",
    "IdentityResolver",
    # Protocols
    "IdentityResolverProtocol",
    # Helpers
    "coerce_identity_key",
    "normalize_domain",
]

# Only expose IdentityMixin if it exists locally.
if IdentityMixin is not None:  # pragma: no cover
    __all__.append("IdentityMixin")

# simcore_ai/types/identity/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .exceptions import IdentityError

"""
Identity (namespace, kind, name)

This module provides a *dumb* container for identity values. It intentionally
does not perform any inference, normalization, token stripping, or validation
beyond minimal string parsing in `from_string()`. All derivation/normalization
logic is owned by decorators and helpers (per the implementation plan).

Terminology:
- namespace: top-level grouping (e.g., app/package/org)
- kind:      functional group/type within the namespace (e.g., codec, service)
- name:      specific identifier within the (namespace, kind)

Decorators are responsible for:
- deriving/inferring each part,
- optional token stripping (name only),
- normalization (e.g., lower/slug),
- validation of allowed characters and emptiness,
before constructing this Identity.
"""


@dataclass(frozen=True, slots=True)
class Identity:
    """
    A simple, immutable identity container.

    NOTE: No normalization or validation is applied here. Values are stored as
    provided. Callers (decorators/helpers) must prepare canonical values.
    """
    namespace: str
    kind: str
    name: str

    # canonical tuple for equality/hash/sorting
    @property
    def as_tuple3(self) -> Tuple[str, str, str]:
        return (self.namespace, self.kind, self.name)

    # stable string for logs/metrics
    def to_string(self) -> str:
        """Returns the dot-separated string 'namespace.kind.name'."""
        return f"{self.namespace}.{self.kind}.{self.name}"

    # Let Python dict/set use this efficiently
    def __hash__(self) -> int:
        return hash(self.as_tuple3)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Identity):
            return NotImplemented
        return self.as_tuple3 == other.as_tuple3

    @classmethod
    def from_parts(
            cls,
            namespace: str,
            kind: str,
            name: str,
    ) -> "Identity":
        """
        Construct an Identity directly from parts.
        Callers must supply already-derived/validated values.
        """
        return cls(namespace=namespace, kind=kind, name=name)

    @classmethod
    def from_string(cls, value: str) -> "Identity":
        """
        Parse a dot-separated string 'namespace.kind.name' into an Identity.

        This method performs only minimal structural parsing (exactly 3 parts).
        It does not normalize or validate character sets; callers should do so upstream.
        """
        if value is None:
            raise IdentityError("Identity string cannot be None")
        try:
            raw = str(value).strip()
        except Exception as e:
            raise IdentityError("Identity string is not coercible to str") from e
        if not raw:
            raise IdentityError("Identity string cannot be empty")
        parts = raw.split(".")
        if len(parts) != 3:
            raise IdentityError(f"Invalid identity format {value!r}; expected 'namespace.kind.name'")
        namespace, kind, name = parts
        return cls(namespace=namespace, kind=kind, name=name)


def parse_identity_str(value: str) -> Identity:
    """Strictly parse 'namespace.kind.name' into an Identity (no normalization)."""
    return Identity.from_string(value)

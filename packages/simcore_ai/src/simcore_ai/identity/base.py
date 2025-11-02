from __future__ import annotations

"""
Identity (namespace, kind, name)

This module provides a small, immutable container for identity values that now
**validates** inputs (type, emptiness, length, and allowed characters) but does
**no normalization or inference**. All derivation/normalization/token-stripping
logic remains the responsibility of resolvers/decorators/utilities upstream.

Terminology:
- namespace: top-level grouping (e.g., app/package/org)
- kind:      functional group/type within the namespace (e.g., codec, service)
- name:      specific identifier within the (namespace, kind)
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Union

from .exceptions import IdentityValidationError, IdentityError
from .registry_resolvers import try_resolve_from_ident

__all__ = [
    "Identity",
    "IdentityKey",
    "IdentityError",
    "IdentityValidationError",
    "parse_identity_str",
]

logger = logging.getLogger(__name__)

# Validation constraints (kept here as single source of truth)
_MAX_LEN = 128
_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# For checking
IdentityKey = Union[str, tuple[str, str, str], "Identity"]

def _validate_label(value: str, field: str) -> str:
    """
    Validate a single identity label (namespace/kind/name).

    Rules:
    - must be a string
    - trimmed value cannot be empty
    - length ≤ 128
    - allowed characters: A–Z, a–z, 0–9, dot (.), underscore (_), hyphen (-)

    Returns the trimmed value on success, raises IdentityError on failure.
    """
    if not isinstance(value, str):
        raise IdentityValidationError(f"{field} must be a string (got {type(value)!r})")
    s = value.strip()
    if not s:
        raise IdentityValidationError(f"{field} cannot be empty")
    if len(s) > _MAX_LEN:
        raise IdentityValidationError(f"{field} too long (> {_MAX_LEN})")
    if not _ALLOWED_RE.match(s):
        raise IdentityValidationError(f"{field} contains illegal characters: {value!r}")
    return s


@dataclass(frozen=True, slots=True)
class Identity:
    """
    An immutable identity container with **validation**.

    Note
    ----
    - No normalization/inference is applied here. Callers (resolvers/decorators)
      must prepare canonical values.
    - Validation is enforced in `__post_init__` so any Identity instance
      created by any constructor is guaranteed valid.
    """

    namespace: str
    kind: str
    name: str

    def __post_init__(self) -> None:
        # Enforce validation on construction (frozen dataclass, no mutation)
        _validate_label(self.namespace, "namespace")
        _validate_label(self.kind, "kind")
        _validate_label(self.name, "name")

    # ------------------- Canonical forms -------------------
    @property
    def as_tuple3(self) -> tuple[str, str, str]:
        """Return the canonical (namespace, kind, name) triple."""
        return self.namespace, self.kind, self.name

    @property
    def as_str(self) -> str:
        """Return the dot-separated string 'namespace.kind.name'."""
        return f"{self.namespace}.{self.kind}.{self.name}"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.as_str

    def __repr__(self) -> str:  # pragma: no cover - convenience
        return f"Identity({self.as_str})"

    # Let Python dict/set use this efficiently
    def __hash__(self) -> int:
        return hash(self.as_tuple3)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Identity):
            return NotImplemented
        return self.as_tuple3 == other.as_tuple3

    # ------------------- Constructors -------------------
    @classmethod
    def from_parts(cls, namespace: str, kind: str, name: str) -> "Identity":
        """Construct an Identity directly from parts (validated)."""
        return cls(namespace=namespace, kind=kind, name=name)

    @classmethod
    def from_string(cls, value: str) -> "Identity":
        """
        Parse a dot-separated string 'namespace.kind.name' into an Identity.

        This method performs structural parsing (exactly 3 parts) and delegates
        validation to the constructor. No normalization is performed.
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
            raise IdentityError(
                f"Invalid identity format {value!r}; expected 'namespace.kind.name'"
            )
        namespace, kind, name = parts
        return cls.from_parts(namespace, kind, name)

    @classmethod
    def validate(cls, namespace: str, kind: str, name: str) -> None:
        """Validate identity parts by attempting construction (raises on failure)."""
        cls(namespace=namespace, kind=kind, name=name)

    # ------------------- Coercion helpers -------------------
    @classmethod
    def get_for(cls, value: "Identity | tuple[str, str, str] | str") -> "Identity":
        """
        Coerce `value` into an Identity (or raise).

        Accepted inputs:
          • Identity          -> returned as-is
          • (ns, kind, name)  -> validated via from_parts(...)
          • "ns.kind.name"    -> parsed via from_string(...)
        """
        if isinstance(value, Identity):
            return value
        if isinstance(value, tuple) and len(value) == 3:
            ns, kd, nm = value
            return cls.from_parts(str(ns), str(kd), str(nm))
        if isinstance(value, str):
            return cls.from_string(value)
        raise IdentityError(f"Unsupported identity input type: {type(value).__name__}")

    @classmethod
    def get(cls, value: "Identity | tuple[str, str, str] | str") -> "Identity":
        """Alias of `get_for` (preferred: use `get_for` in new code)."""
        return cls.get_for(value)

    @classmethod
    def coerce_key(cls, value: "Identity | tuple[str, str, str] | str") -> "Identity":
        """Alias of `get_for` kept for transitional callers."""
        return cls.get_for(value)

    @classmethod
    def try_get(cls, value: "Identity | tuple[str, str, str] | str") -> Identity | None:
        """Best-effort coercion. Returns None instead of raising on failure."""
        try:
            return cls.get_for(value)
        except Exception:
            return None

    # ------------------- Registry resolution (delegating) -------------------
    @classmethod
    def try_resolve(
            cls,
            target: "Identity | tuple[str, str, str] | str | type",
            registry_or_type: Any = None,
    ) -> Any | None:
        """
        Best-effort lookup of a registry item by identity.

        Thin wrapper that **defers** to `identity.registry_resolvers.try_resolve_from_ident(...)`
        so there is a single source of truth for coercion and lookup.
        """
        return try_resolve_from_ident(target, registry_or_type=registry_or_type)


# ------------------- Free helpers -------------------

def parse_identity_str(value: str) -> Identity:
    """Strictly parse 'namespace.kind.name' into an Identity (no normalization)."""
    return Identity.from_string(value)

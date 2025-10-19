# simcore_ai/types/identity/base.py
from __future__ import annotations
from dataclasses import dataclass
import re

from typing import Tuple
from .exceptions import IdentityError

"""
This module defines the `Identity` class, which provides a standardized way to represent
an identity composed of three hierarchical components: origin, bucket, and name.

Normalization rules applied to each component:
- If the input is None or empty, it defaults to "default".
- Leading and trailing whitespace is stripped.
- All characters are converted to lowercase.
- Spaces and hyphens are replaced with underscores.
"""


def _norm(s: str | None) -> str:
    """Normalize a string to a canonical representation.

    Replaces:
        - Whitespace with underscores
        - Hyphens with underscores
        - Dots/colons with underscores
        - Uppercase with Lowercase
        - Leading and trailing whitespace
        - Empty strings with "default"

    Args:
        s: The string to normalize.

    Returns:
        Normed string or "default"
    """
    if s is None:
        return "default"
    try:
        s = str(s)
    except Exception as e:
        # Coerce failures are identity-level issues
        raise IdentityError(f"Unable to normalize identity component: {s!r}") from e
    s = (
        s.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace(":", "_")
    )
    return s or "default"


@dataclass(frozen=True, slots=True)
class Identity:
    """
    Represents a hierarchical identity with three components:
    - origin: top-level grouping (e.g., project or origin)
    - bucket: functional group within the origin
    - name: specific operation or entity name

    Each field is normalized by stripping whitespace, converting to lowercase,
    and replacing spaces and hyphens with underscores. Empty or None values
    default to "default".
    """
    origin: str = "default"
    bucket: str = "default"
    name: str = "default"

    def __post_init__(self):
        # dataclass with frozen=True: use object.__setattr__
        object.__setattr__(self, "origin", _norm(self.origin))
        object.__setattr__(self, "bucket", _norm(self.bucket))
        object.__setattr__(self, "name", _norm(self.name))

    @property
    def origin_str(self) -> str:
        """Returns the canonical string representation of the identity."""
        return self.to_string()

    @classmethod
    def from_parts(
            cls,
            origin: str | None = None,
            bucket: str | None = None,
            name: str | None = None,
    ) -> "Identity":
        """
        Creates an Identity instance, normalizing missing parts to "default".
        """
        return cls(origin=origin or "default", bucket=bucket or "default", name=name or "default")

    @classmethod
    def from_string(cls, value: str) -> "Identity":
        """
        Parse a canonical identity string 'origin.bucket.name' into an Identity.
        Raises IdentityError if the format is invalid.
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
            raise IdentityError(f"Invalid identity format {value!r}; expected 'origin.bucket.name'")
        orig, buck, nm = parts
        return cls(origin=orig, bucket=buck, name=nm)

    # canonical tuple for equality/hash/sorting
    @property
    def as_tuple3(self) -> Tuple[str, str, str]:
        return (self.origin, self.bucket, self.name)

    # stable string for logs/metrics
    def to_string(self) -> str:
        return f"{self.origin}.{self.bucket}.{self.name}"

    # Let Python dict/set use this efficiently
    def __hash__(self) -> int:
        return hash(self.as_tuple3)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Identity):
            return NotImplemented
        return self.as_tuple3 == other.as_tuple3


def parse_identity_str(value: str) -> Identity:
    """Strictly parse an identity in the form "origin.bucket.name" into an Identity.

    Raises IdentityError if the input is not exactly three dot-separated parts.
    """
    return Identity.from_string(value)

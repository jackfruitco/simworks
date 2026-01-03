# orchestrai/identity/identity.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import NamedTuple, Union, ClassVar, Any

from .exceptions import IdentityValidationError, IdentityError, IdentityResolutionError
from .protocols import IdentityProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "Identity",
    "IdentityKey",
    "IdentityLike",
]


# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------

class IdentityKey(NamedTuple):
    """Lightweight quadruple for (domain, namespace, group, name)."""

    domain: str
    namespace: str
    group: str
    name: str


# Union type callers can use for “identity-like” inputs
IdentityLike = Union["Identity", IdentityKey, tuple[str, str, str, str], str]

# -----------------------------------------------------------------------------
# Validation constraints (single source of truth)
# -----------------------------------------------------------------------------

_MAX_LEN = 128
_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_label(value: str, field: str) -> str:
    """
    Validate a single identity label (domain/namespace/group/name).

    Rules:
    - must be a string
    - trimmed value cannot be empty
    - length ≤ 128
    - allowed characters: A–Z, a–z, 0–9, dot (.), underscore (_), hyphen (-)

    Returns the trimmed value on success, raises IdentityValidationError on failure.
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


# -----------------------------------------------------------------------------
# Identity (Value Object)
# -----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Identity:
    """
    Immutable identity with validation. Canonical form uses (domain, namespace, group, name).

    Canonical string: "domain.namespace.group.name".
    """

    domain: str
    namespace: str
    group: str
    name: str

    # Typed placeholder for the dynamically attached facade (set in __init__.py)
    resolve: ClassVar[Any]

    # ------------------- Validation -------------------
    def __post_init__(self) -> None:
        _validate_label(self.domain, "domain")
        _validate_label(self.namespace, "namespace")
        _validate_label(self.group, "group")
        _validate_label(self.name, "name")

    # ------------------- Canonical forms -------------------
    @property
    def as_tuple(self) -> tuple[str, str, str, str]:
        return self.domain, self.namespace, self.group, self.name

    @property
    def as_tuple4(self) -> tuple[str, str, str, str]:
        return self.as_tuple

    @property
    def as_str(self) -> str:
        """Return canonical dot form: 'domain.namespace.group.name'."""
        return f"{self.domain}.{self.namespace}.{self.group}.{self.name}"

    @property
    def key(self) -> IdentityKey:
        """Return (domain, namespace, group, name) tuple."""
        return IdentityKey(self.domain, self.namespace, self.group, self.name)

    @property
    def label(self) -> str:
        """Return 'domain.namespace.group.name' string."""
        return self.as_str

    # Backward-compatible alias (read-only)
    @property
    def kind(self) -> str:
        return self.group

    def __str__(self) -> str:  # pragma: no cover
        return self.as_str

    def __repr__(self) -> str:  # pragma: no cover
        return f"Identity({self.as_str})"

    def __hash__(self) -> int:
        return hash(self.as_tuple)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Identity):
            return NotImplemented
        return self.as_tuple == other.as_tuple

    # ------------------- Constructors -------------------
    @classmethod
    def get(cls, value: IdentityLike) -> Identity:
        """Get an Identity instance from any IdentityLike object.

        :param value: An Identity-like object
        :return: An Identity instance

        :raises IdentityError: If the input cannot be converted to an Identity.
        """

        def _from_key(key: IdentityKey) -> Identity:
            return cls(domain=key.domain, namespace=key.namespace, group=key.group, name=key.name)

        def _from_tuple(value_: tuple[str, str, str, str]) -> "Identity":
            if len(value_) != 4:
                raise IdentityError(
                    f"Expected a tuple of 4 parts (domain, namespace, group, name); got {value_!r}"
                )
            dm_, ns_, gp_, nm_ = value_
            return cls(domain=str(dm_), namespace=str(ns_), group=str(gp_), name=str(nm_))

        def _from_str(value_: str) -> Identity:
            parts_ = [p.strip() for p in value_.split(".", 3)]
            if len(parts_) != 4 or any(p == "" for p in parts_):
                raise IdentityError(f"Expected 'domain.namespace.group.name', got {value!r}")
            dm_, ns_, gp_, nm_ = parts_
            return cls(domain=dm_, namespace=ns_, group=gp_, name=nm_)

        def _fallback(value_: object) -> Identity:
            if not isinstance(value_, str):
                raise IdentityError(f"Unrecognized identity input type: {type(value_).__name__}")

            s = value_.strip("()").replace("'", "").replace('"', "")
            parts = [p.strip() for p in s.split(",")]
            if len(parts) == 4:
                return cls(domain=parts[0], namespace=parts[1], group=parts[2], name=parts[3])
            raise IdentityResolutionError(
                f"Unrecognized identity string format: {value!r}. "
                "Use 'domain.namespace.group.name' or '(domain, namespace, group, name)'."
            )

        # Fast-path for Identity
        if isinstance(value, cls):
            return value

        # Named tuple
        if isinstance(value, IdentityKey):
            return _from_key(value)

        # Tuple4
        if isinstance(value, tuple):
            return _from_tuple(value)

        # String inputs
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                raise IdentityError("Identity string cannot be empty")
            # Prefer canonical dot-string
            if "." in raw and "," not in raw:
                return _from_str(raw)

            # Fallback: tuple-like string "(a, b, c)"
            return _fallback(raw)

        raise IdentityError(f"Unsupported identity input type: {type(value).__name__}")

    @classmethod
    def get_for(cls, value: IdentityLike | IdentityProtocol) -> Identity:
        """
        Resolve the Identity for a component or IdentityLike:
          • If `value` exposes `.identity`, coerce and return that.
          • Otherwise, treat `value` itself as IdentityLike and coerce.
        Accepts either a component *instance* or *class* with an `identity` attribute.
        """
        # Component instance or class with `.identity`
        ident_attr = getattr(value, "identity", None)
        if ident_attr is not None:
            return cls.get(ident_attr)
        # Otherwise, allow IdentityLike directly
        return cls.get(value)  # may raise IdentityError

    @classmethod
    def validate(cls, domain: str, namespace: str, group: str, name: str) -> None:
        """Validate parts by attempting construction (raises on failure)."""
        cls(domain=domain, namespace=namespace, group=group, name=name)

    # ------------------- Coercion helpers -------------------
    @classmethod
    def try_get(cls, value: IdentityLike) -> Identity | None:
        """Best-effort coercion. Returns None instead of raising on failure."""
        try:
            return cls.get(value)
        except Exception:
            return None

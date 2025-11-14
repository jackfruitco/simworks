from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import NamedTuple, Union, ClassVar, Any

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
    """Lightweight triple for (namespace, kind, name)."""
    namespace: str
    kind: str
    name: str


# Union type callers can use for “identity-like” inputs
IdentityLike = Union["Identity", IdentityKey, tuple[str, str, str], str]

# -----------------------------------------------------------------------------
# Validation constraints (single source of truth)
# -----------------------------------------------------------------------------

_MAX_LEN = 128
_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Prefer central exceptions if available; otherwise use local fallbacks.
try:
    from .exceptions import IdentityValidationError, IdentityError
except Exception:  # pragma: no cover
    class IdentityError(ValueError):
        """Generic identity error."""
        pass


    class IdentityValidationError(IdentityError):
        """Validation failure for identity components."""
        pass


def _validate_label(value: str, field: str) -> str:
    """
    Validate a single identity label (namespace/kind/name).

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
    Immutable identity with validation. Canonical form uses (namespace, kind, name).

    Canonical string: "namespace.kind.name".
    """

    namespace: str
    kind: str
    name: str

    # Typed placeholder for the dynamically attached facade (set in __init__.py)
    resolve: ClassVar[Any]

    # ------------------- Validation -------------------
    def __post_init__(self) -> None:
        _validate_label(self.namespace, "namespace")
        _validate_label(self.kind, "kind")
        _validate_label(self.name, "name")

    # ------------------- Canonical forms -------------------
    @property
    def as_tuple3(self) -> tuple[str, str, str]:
        return self.namespace, self.kind, self.name

    @property
    def as_str(self) -> str:
        """Return canonical dot form: 'namespace.kind.name'."""
        return f"{self.namespace}.{self.kind}.{self.name}"

    @property
    def key(self) -> IdentityKey:
        """Return (namespace, kind, name) tuple."""
        return IdentityKey(self.namespace, self.kind, self.name)

    @property
    def label(self) -> str:
        """Return 'namespace.kind.name' string."""
        return self.as_str

    def __str__(self) -> str:  # pragma: no cover
        return self.as_str

    def __repr__(self) -> str:  # pragma: no cover
        return f"Identity({self.as_str})"

    def __hash__(self) -> int:
        return hash(self.as_tuple3)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Identity):
            return NotImplemented
        return self.as_tuple3 == other.as_tuple3

    # ------------------- Constructors -------------------
    @classmethod
    def get(cls, value: IdentityLike) -> "Identity":
        """Canonical public API: coerce any IdentityLike into an Identity."""

        def _from_key(key: IdentityKey) -> "Identity":
            return cls(namespace=key.namespace, kind=key.kind, name=key.name)

        def _from_tuple(value_: tuple[str, str, str]) -> "Identity":
            ns_, kd_, nm_ = value_
            return cls(namespace=str(ns_), kind=str(kd_), name=str(nm_))

        def _from_str(value_: str) -> "Identity":
            parts_ = [p.strip() for p in value_.split(".", 2)]
            if len(parts_) != 3 or any(p == "" for p in parts_):
                raise IdentityError(f"Expected 'namespace.kind.name', got {value!r}")
            ns_, kd_, nm_ = parts_
            return cls(namespace=ns_, kind=kd_, name=nm_)

        def _fallback(value_: object) -> "Identity":
            if not isinstance(value_, str):
                raise IdentityError(f"Unrecognized identity input type: {type(value_).__name__}")

            s = value_.strip("()").replace("'", "").replace('"', "")
            parts = [p.strip() for p in s.split(",")]
            if len(parts) == 3:
                return cls(namespace=parts[0], kind=parts[1], name=parts[2])
            raise IdentityError(
                f"Unrecognized identity string format: {value!r}. "
                "Use 'namespace.kind.name' or '(namespace, kind, name)'."
            )

        # Fast-path for Identity
        if isinstance(value, cls):
            return value

        # Named tuple
        if isinstance(value, IdentityKey):
            return _from_key(value)

        # Tuple3
        if isinstance(value, tuple) and len(value) == 3:
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
    def get_for(cls, value: IdentityLike | IdentityProtocol) -> "Identity":
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
    def validate(cls, namespace: str, kind: str, name: str) -> None:
        """Validate parts by attempting construction (raises on failure)."""
        cls(namespace=namespace, kind=kind, name=name)

    # ------------------- Coercion helpers -------------------
    @classmethod
    def try_get(cls, value: IdentityLike) -> "Identity | None":
        """Best-effort coercion. Returns None instead of raising on failure."""
        try:
            return cls.get(value)
        except Exception:
            return None

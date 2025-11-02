# simcore_ai/types/identity/exceptions.py
from __future__ import annotations

from simcore_ai.exceptions.base import SimCoreError


class IdentityError(SimCoreError): ...


class IdentityCollisionError(Exception):
    """Raised when a different class attempts to register an existing identity."""


class IdentityValidationError(Exception):
    """Raised when identity is malformed (arity/empties/non-strings)."""

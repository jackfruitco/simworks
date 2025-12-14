# orchestrai/types/identity/exceptions.py


from orchestrai.exceptions.base import SimCoreError


class IdentityError(SimCoreError): ...


class IdentityCollisionError(IdentityError):
    """Raised when a different class attempts to register an existing identity."""


class IdentityValidationError(IdentityError):
    """Raised when identity is malformed (arity/empties/non-strings)."""

class IdentityResolutionError(IdentityError):
    """Raised when identity resolution fails. Is the input identity-like?"""

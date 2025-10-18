"""Registry exceptions"""
from .base import SimCoreError


# ----------------------------------------------------------------------------
# Registry errors
# ----------------------------------------------------------------------------
class RegistryError(SimCoreError): ...


class RegistryDuplicateError(RegistryError): ...


class RegistryLookupError(RegistryError): ...

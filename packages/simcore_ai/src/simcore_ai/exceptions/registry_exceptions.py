# simcore_ai/exceptions/registry_exceptions.py
"""Registry exceptions"""
from .base import SimCoreError


# ----------------------------------------------------------------------------
# Registry errors
# ----------------------------------------------------------------------------
class RegistryError(SimCoreError): ...


class RegistryDuplicateError(RegistryError): ...


class RegistryLookupError(RegistryError): ...

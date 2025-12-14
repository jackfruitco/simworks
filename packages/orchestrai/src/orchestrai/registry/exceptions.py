# orchestrai/exceptions/registry_exceptions.py
"""Registry exceptions"""
from orchestrai.exceptions.base import SimCoreError


# ----------------------------------------------------------------------------
# Registry errors
# ----------------------------------------------------------------------------
class RegistryError(SimCoreError): ...


class RegistryDuplicateError(RegistryError): ...


class RegistryNotFoundError(RegistryError): ...


class RegistryCollisionError(RegistryError): ...


class RegistryLookupError(RegistryError): ...


class RegistryFrozenError(RuntimeError, RegistryError): ...

# simcore_ai/exceptions/registry_exceptions.py
"""Registry exceptions"""
from simcore_ai.exceptions.base import SimCoreError


# ----------------------------------------------------------------------------
# Registry errors
# ----------------------------------------------------------------------------
class RegistryError(SimCoreError): ...


class RegistryDuplicateError(RegistryError): ...


class RegistryNotFoundError(RegistryError): ...


class RegistryCollisionError(RegistryError): ...


class RegistryLookupError(RegistryError): ...


class RegistryFrozenError(RuntimeError, RegistryError): ...

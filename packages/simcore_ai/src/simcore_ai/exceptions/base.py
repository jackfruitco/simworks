


class SimCoreError(Exception):
    """Base for all simcore_ai exceptions."""


# ----------------------------------------------------------------------------
# Other errors
# ----------------------------------------------------------------------------
class RetryableError: ...


class NonRetryableError: ...

# ----------------------------------------------------------------------------
# Registry errors
# ----------------------------------------------------------------------------
class RegistryError(SimCoreError): ...


class RegistryDuplicateError(RegistryError): ...


class RegistryLookupError(RegistryError): ...

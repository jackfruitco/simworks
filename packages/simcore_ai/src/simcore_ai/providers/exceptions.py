from simcore_ai.exceptions import RetryableError, NonRetryableError
from simcore_ai.exceptions.base import SimCoreError


class ProviderError(SimCoreError): ...


class ProviderCallError(ProviderError, RetryableError): ...


class ProviderResponseError(ProviderError): ...


class ProviderSchemaUnsupported(ProviderError, NonRetryableError): ...

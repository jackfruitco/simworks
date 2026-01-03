# orchestrai/components/providerkit/exceptions.py


from orchestrai.exceptions.base import SimCoreError, RetryableError, NonRetryableError


class ProviderError(SimCoreError): ...


class ProviderConfigurationError(ProviderError): ...


class ProviderCallError(ProviderError, RetryableError): ...


class ProviderResponseError(ProviderError): ...


class ProviderSchemaUnsupported(ProviderError, NonRetryableError): ...

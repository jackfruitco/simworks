# simcore_ai/providers/exceptions.py
from __future__ import annotations

from simcore_ai.exceptions.base import SimCoreError, RetryableError, NonRetryableError


class ProviderError(SimCoreError): ...


class ProviderCallError(ProviderError, RetryableError): ...


class ProviderResponseError(ProviderError): ...


class ProviderSchemaUnsupported(ProviderError, NonRetryableError): ...

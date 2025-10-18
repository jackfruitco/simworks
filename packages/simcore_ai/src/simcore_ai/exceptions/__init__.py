"""
This module defines a list of exception classes used across various components
of the system. The exceptions are categorized into base errors, codec-specific
errors, provider-specific errors, and identity-related errors. These exception
classes allow for standardized error handling within different parts of the
application.

The module also imports the necessary base exception definitions and
conditionally includes specific types of exceptions under `__all__` for use
when needed.

Attributes:
    __all__ (list of str): A list of exception class names exposed by this module,
        categorized as follows:
        - Core Errors: Errors related to the core functionalities, such as retry,
          non-retriable exceptions, and registry issues.
        - Codec Errors: Exception classes specific to codec-related failures, such
          as schema or decoding errors.
        - Provider Errors: Definitions for errors occurring in provider operations,
          such as call or response-related problems.
        - Identity Errors: Exception classes for identity-related issues.

TODO: Consider re-export of sub-package exceptions (avoid circular imports)
"""
# from .base import *
# from .registry_exceptions import *
# from ..services.exceptions import *
# from ..codecs.exceptions import *
# from ..providers.exceptions import *
# from ..types.identity.exceptions import *
# from ..types.exceptions import *
# from ..client.exceptions import *

__all__ = [
    # --- Core (./base.py) ---
    # "SimCoreError", "RetryableError", "NonRetryableError",
    # "RegistryError", "RegistryLookupError", "RegistryDuplicateError",

    # --- Services ---
    # "ServiceError", "ServiceConfigError", "ServiceCodecResolutionError",
    # "ServiceBuildRequestError", "ServiceStreamError",

    # --- Codecs ---
    # "CodecError", "CodecNotFoundError", "CodecSchemaError", "CodecDecodeError",

    # --- Providers ---
    # "ProviderError", "ProviderCallError", "ProviderResponseError", "ProviderSchemaUnsupported",

    # --- Identity ---
    # "IdentityError",
]
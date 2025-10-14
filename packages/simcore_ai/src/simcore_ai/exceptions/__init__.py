from .base import *
from ..services.exceptions import *
from ..codecs.exceptions import *
from ..providers.exceptions import *
from ..types.exceptions import *  # optional
from ..client.exceptions import *  # optional

__all__ = [
    # --- Core (./base.py) ---
    "SimCoreError", "RetryableError", "NonRetryableError",
    "RegistryError", "RegistryLookupError", "RegistryDuplicateError",

    # --- Services ---
    "ServiceError", "ServiceConfigError", "ServiceCodecResolutionError",
    "ServiceBuildRequestError", "ServiceStreamError",

    # --- Codecs ---
    "CodecError", "CodecNotFoundError", "CodecSchemaError", "CodecDecodeError",

    # --- Providers ---
    "ProviderError", "ProviderCallError", "ProviderResponseError", "ProviderSchemaUnsupported",

    # --- Identity ---
    "IdentityError",
]
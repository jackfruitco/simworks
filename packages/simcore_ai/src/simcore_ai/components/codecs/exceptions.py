# simcore_ai/components/codecs/exceptions.py
from simcore_ai.exceptions.base import SimCoreError
from simcore_ai.registry.exceptions import RegistryLookupError, RegistryDuplicateError, RegistryError

__all__ = [
    "CodecError", "CodecSchemaError", "CodecRegistrationError",
    "CodecDuplicateRegistrationError", "CodecNotFoundError",
    "CodecError", "CodecSchemaError",
    "CodecEncodeError", "CodecDecodeError", "CodecLifecycleError",
]

class CodecError(SimCoreError):
    """Base error for all codec-related failures."""


class CodecSchemaError(CodecError):
    """Schema class missing or invalid during validation setup."""


class CodecEncodeError(CodecError):
    """Failed to encode a request or attach provider hints."""


class CodecDecodeError(CodecError):
    """Failed to decode or validate structured response output."""


class CodecLifecycleError(CodecError):
    """General setup/teardown failure in codec lifecycle."""


class CodecRegistrationError(RegistryError, CodecError):
    """Unable to register codec in registry."""


class CodecDuplicateRegistrationError(CodecRegistrationError, RegistryDuplicateError):
    """Attempted to register a codec with a duplicate identity."""


class CodecNotFoundError(CodecError, RegistryLookupError):
    """Requested codec not found in registry."""
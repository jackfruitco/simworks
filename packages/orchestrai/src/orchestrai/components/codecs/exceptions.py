# orchestrai/components/codecs/exceptions.py
from orchestrai.exceptions.base import SimCoreError
from orchestrai.registry.exceptions import RegistryLookupError, RegistryDuplicateError, RegistryError

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
    """Failed to encode a request or attach backend hints."""


class CodecDecodeError(CodecError):
    """Failed to decode or validate structured response output.

    By default, these errors are non-retriable (immediate failure).
    Set `retriable=True` for transient failures that may succeed on retry.
    """

    def __init__(self, message: str, *, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


class CodecLifecycleError(CodecError):
    """General setup/teardown failure in codec lifecycle."""


class CodecRegistrationError(RegistryError, CodecError):
    """Unable to register codec in registry."""


class CodecDuplicateRegistrationError(CodecRegistrationError, RegistryDuplicateError):
    """Attempted to register a codec with a duplicate identity."""


class CodecNotFoundError(CodecError, RegistryLookupError):
    """Requested codec not found in registry."""
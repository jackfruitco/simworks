"""Compatibility codec base classes/exceptions for legacy imports."""

from .codec import BaseCodec
from .exceptions import CodecDecodeError, CodecNotFoundError

__all__ = ["BaseCodec", "CodecDecodeError", "CodecNotFoundError"]

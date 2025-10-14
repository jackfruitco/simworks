"""
Core LLM Codec Package

Codecs define the translation layer between normalized AI data structures
(e.g., `NormalizedAIResponse`) and application-specific representations. Each
codec implements encode/decode logic and may declare a response schema.

This package provides:
    - `BaseLLMCodec`: the framework-agnostic base class for codecs
    - `CodecRegistry`: lightweight registry for global codec lookup
    - `get_codec(namespace, name)`: helper for registry retrieval
    - `register_codec`: decorator for automatic registration on import

Usage Example:
    from simcore_ai.codecs import BaseLLMCodec, register_codec

    @codec
    class ExampleCodec(BaseLLMCodec):
        name = "example"
        namespace = "core"

        def decode_response(self, response, **context):
            # convert structured LLM output to internal DTOs
            return response

Once imported, this codec can be automatically resolved by a
`BaseLLMService` or `DjangoBaseLLMService` with a matching identity.
"""

from .base import BaseLLMCodec
from .decorators import codec
from .registry import CodecRegistry, get_codec

__all__ = [
    "BaseLLMCodec",
    "CodecRegistry",
    "get_codec",
    # decorator
    "codec",
]

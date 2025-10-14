"""
Core codec registration decorator.

This decorator instantiates and registers a `BaseLLMCodec` subclass with the
central `CodecRegistry` in the `simcore_ai.codecs` package. When the decorated
class is imported, it is automatically registered for lookup and use by
`BaseLLMService` instances.

Example:
    from simcore_ai.codecs.decorators import register_codec
    from simcore_ai.codecs import BaseLLMCodec

    @codec
    class ChatLabCodec(BaseLLMCodec):
        name = "chatlab"
        namespace = "chatlab"

        def decode_response(self, response, **context):
            # interpret LLM response here
            return response

When the module is imported, the codec instance is created and registered in
the core registry for use by all core services.
"""
from __future__ import annotations

from typing import Type

from simcore_ai.codecs import BaseLLMCodec
from simcore_ai.codecs.registry import CodecRegistry
from simcore_ai.exceptions import RegistryDuplicateError


def codec(codec_cls: Type[BaseLLMCodec]) -> Type[BaseLLMCodec]:
    """
    Class decorator to instantiate and register a codec in the core registry.
    The codec class should define:
      - name: str (required)
      - namespace: str (optional; defaults to 'default')
    """
    instance = codec_cls()
    try:
        CodecRegistry.register(instance)
    except RegistryDuplicateError:
        # Allow idempotent re-registration during autoreload
        pass
    return codec_cls

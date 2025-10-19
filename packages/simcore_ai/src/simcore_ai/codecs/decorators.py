"""
Core codec registration decorator

Registers a `BaseLLMCodec` subclass with the global `CodecRegistry`.
Codecs must now define `origin`, `bucket`, and `name`, replacing the legacy
`namespace` attribute.

Example:
    from simcore_ai.codecs.decorators import codec
    from simcore_ai.codecs import BaseLLMCodec

    @codec
    class ChatLabPatientCodec(BaseLLMCodec):
        origin = "chatlab"
        bucket = "patient"
        name = "default"

        def decode_response(self, response, **context):
            return response
"""

from __future__ import annotations
import logging
from typing import Type
from simcore_ai.codecs import BaseLLMCodec
from simcore_ai.codecs.registry import CodecRegistry
from simcore_ai.exceptions.registry_exceptions import RegistryDuplicateError

logger = logging.getLogger(__name__)


def codec(codec_cls: Type[BaseLLMCodec]) -> Type[BaseLLMCodec]:
    """Decorator that instantiates and registers a codec using v3 identity fields."""
    instance = codec_cls()

    # Validate required identity attributes
    if not getattr(instance, "origin", None):
        raise TypeError(f"Codec {codec_cls.__name__} missing required field 'origin'")
    if not getattr(instance, "bucket", None):
        raise TypeError(f"Codec {codec_cls.__name__} missing required field 'bucket'")

    try:
        CodecRegistry.register(instance)
        logger.info(
            "Registered codec: %s/%s/%s",
            instance.origin,
            instance.bucket,
            getattr(instance, "name", "<unnamed>"),
        )
    except RegistryDuplicateError:
        # Allow idempotent re-registration during autoreload
        pass

    return codec_cls

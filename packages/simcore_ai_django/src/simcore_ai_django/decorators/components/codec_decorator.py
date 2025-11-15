

from simcore_ai.registry import BaseRegistry
from simcore_ai_django.decorators import DjangoBaseDecorator

"""
Core codec decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "codec" if not provided).
- Registers the class in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

from typing import Any, Type, TypeVar
import logging

from ..base import DjangoBaseDecorator
from simcore_ai_django.components import DjangoBaseCodec
from simcore_ai.components.codecs.base import BaseCodec
from simcore_ai.registry.singletons import codecs as codec_registry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class DjangoCodecDecorator(DjangoBaseDecorator):
    """
    Codec decorator specialized for BaseCodec subclasses.

    Usage
    -----
        from simcore_ai.decorators.codec import codec

        @codec
        class MyCodec(BaseCodec):
            ...

        # or with explicit hints
        @codec(namespace="simcore", name="my_codec")
        class JSONCodec(BaseCodec):
            ...
    """
    default_kind = "default"

    def get_registry(self) -> BaseRegistry:
        # Always register into the codecs registry
        return codec_registry

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register codec classes
        if not issubclass(candidate, BaseCodec):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseCodec to use @codec"
            )
        super().register(candidate)

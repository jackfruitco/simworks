
"""
Core codec decorator.

- Derives & pins identity via IdentityResolver (kind/namespace/name via resolver + hints).
- Registers codec classes in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
- Enforces that only BaseCodec subclasses can be decorated.
"""
import logging
from typing import Any, Type, TypeVar

from simcore_ai.registry import BaseRegistry
from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.components.codecs.codecs import BaseCodec
from simcore_ai.registry.singletons import codecs as codec_registry

__all__ = ("CodecDecorator", "codec")

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class CodecDecorator(BaseDecorator):
    """
    Codec decorator specialized for BaseCodec subclasses.

    Usage
    -----
        from simcore_ai.decorators.codec import codec

        @codec
        class MyCodec(BaseCodec):
            ...

        # or with explicit hints
        @codec(namespace="openai", kind="responses", name="json")
        class OpenAIJSONCodec(BaseCodec):
            ...
    """

    def get_registry(self) -> BaseRegistry:
        """Return the global codecs registry singleton."""
        return codec_registry

    def register(self, candidate: Type[Any]) -> None:
        """Register a codec class after guarding its base type.

        Ensures only BaseCodec subclasses are registered into the codecs registry.
        """
        if not issubclass(candidate, BaseCodec):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseCodec to use @codec"
            )
        super().register(candidate)


# Public instance used as the decorator in app code
codec = CodecDecorator()

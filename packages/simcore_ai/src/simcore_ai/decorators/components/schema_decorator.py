

from simcore_ai.registry import BaseRegistry

"""
Core codec decorator.

- Derives & pins identity via IdentityResolver (kind defaults to "codec" if not provided).
- Registers the class in the global `codecs` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

from typing import Any, Type, TypeVar
import logging

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.components.schemas import BaseOutputSchema
from simcore_ai.registry.singletons import schemas as _Registry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[Any])


class SchemaDecorator(BaseDecorator):
    """
    Codec decorator specialized for BaseOutputSchema subclasses.

    Usage
    -----
        from simcore_ai.decorators import schema

        @schema
        class MySchema(BaseOutputSchema):
            ...

        # or with explicit hints
        @schema(namespace="simcore", name="my_schema")
        class MySchema(BaseOutputSchema):
            ...
    """

    def get_registry(self) -> BaseRegistry:
        # Always register into the schema registry
        return _Registry

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register schema classes
        if not issubclass(candidate, BaseOutputSchema):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseOutputSchema to use @schema"
            )
        super().register(candidate)

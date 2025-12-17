"""
Core schema decorator.

- Derives & pins identity via IdentityResolver (domain/namespace/group/name via resolver + hints).
- Registers the class in the global `schemas` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
"""

from typing import Any, Type, TypeVar
import logging

from orchestrai.decorators.base import BaseDecorator
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.identity.domains import SCHEMAS_DOMAIN
from orchestrai.registry import ComponentRegistry
from orchestrai.registry import schemas as schema_registry

logger = logging.getLogger(__name__)

__all__ = ("SchemaDecorator",)

T = TypeVar("T", bound=Type[Any])


class SchemaDecorator(BaseDecorator):
    """
    Schema decorator specialized for BaseOutputSchema subclasses.

    Usage
    -----
        from orchestrai.decorators import schema

        @schema
        class MySchema(BaseOutputSchema):
            ...

        # or with explicit hints
        @schema(namespace="simcore", group="schemas", name="my_schema")
        class MySchema(BaseOutputSchema):
            ...
    """

    default_domain = SCHEMAS_DOMAIN

    def get_registry(self) -> ComponentRegistry:
        # Always register into the schema registry
        return schema_registry

    # Human-friendly log label
    log_category = "output_schemas"

    def register(self, candidate: Type[Any]) -> None:
        # Guard: ensure we only register schema classes
        if not issubclass(candidate, BaseOutputSchema):
            raise TypeError(
                f"{candidate.__module__}.{candidate.__name__} must subclass BaseOutputSchema to use @schema"
            )
        super().register(candidate)

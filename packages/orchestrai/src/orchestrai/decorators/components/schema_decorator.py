"""
Core schema decorator.

- Derives & pins identity via IdentityResolver (domain/namespace/group/name via resolver + hints).
- Registers the class in the global `schemas` registry.
- Preserves the `.identity` descriptor from `IdentityMixin` (pinning only, no attr overwrites).
- Validates schemas against provider-specific requirements (OpenAI, etc.)
- Tags schemas with provider compatibility metadata
"""

from typing import Any, Type, TypeVar
import logging

from orchestrai.decorators.base import BaseDecorator
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.identity.domains import SCHEMAS_DOMAIN
from orchestrai.registry import ComponentRegistry
from orchestrai.registry import schemas as schema_registry

# Provider validation config
try:
    from orchestrai.contrib.provider_backends.openai.schema.validate import validate_openai_schema
    PROVIDER_VALIDATION_CONFIG = {
        "openai": {
            "validator": validate_openai_schema,
            "tag": "supports_openai",
        },
        # Future providers can be added here:
        # "anthropic": {
        #     "validator": validate_anthropic_schema,
        #     "tag": "supports_anthropic",
        # },
    }
except ImportError:
    # Graceful degradation if OpenAI backend not available
    PROVIDER_VALIDATION_CONFIG = {}
    logger.warning("OpenAI schema validation not available (import error)")

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
        @schema(namespace="orchestrai", group="schemas", name="my_schema")
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

        # Validate schema against provider requirements and tag compatibility
        self._validate_and_tag_schema(candidate)

        super().register(candidate)

    def _validate_and_tag_schema(self, schema_cls: Type[BaseOutputSchema]) -> None:
        """Validate schema against provider requirements and tag compatibility.

        This method:
        1. Generates JSON Schema from the Pydantic model
        2. Validates against each provider's requirements
        3. Tags the schema class with provider compatibility metadata
        4. Caches the validated schema for reuse
        """
        # Generate JSON Schema from Pydantic model
        try:
            json_schema = schema_cls.model_json_schema()
        except Exception as e:
            logger.error(
                f"Failed to generate JSON schema for {schema_cls.__name__}: {e}"
            )
            # If we can't generate schema, we can't validate or use it
            raise ValueError(
                f"Cannot generate JSON schema for {schema_cls.__name__}: {e}"
            ) from e

        # Initialize provider compatibility metadata
        provider_compatibility = {}

        # Validate against each configured provider
        for provider_name, config in PROVIDER_VALIDATION_CONFIG.items():
            validator_func = config.get("validator")
            tag_name = config.get("tag", f"supports_{provider_name}")

            if validator_func is None:
                # Provider has no validators - automatically compatible
                provider_compatibility[tag_name] = True
                logger.debug(
                    f"{schema_cls.__name__}: {provider_name} has no validators, marking compatible"
                )
                continue

            # Run validation (strict=True means it will raise on failure)
            try:
                validator_func(json_schema, schema_cls.__name__, strict=True)
                provider_compatibility[tag_name] = True
                logger.info(
                    f"✓ {schema_cls.__name__}: Compatible with {provider_name}"
                )
            except ValueError as e:
                # Validation failed - schema is NOT compatible with this provider
                provider_compatibility[tag_name] = False
                logger.error(
                    f"✗ {schema_cls.__name__}: Incompatible with {provider_name}: {e}"
                )
                # Re-raise to fail fast on incompatible schemas
                raise ValueError(
                    f"Schema {schema_cls.__name__} is not compatible with {provider_name}: {e}"
                ) from e

        # Tag the schema class with metadata
        setattr(schema_cls, "_provider_compatibility", provider_compatibility)
        setattr(schema_cls, "_validated_schema", json_schema)

        logger.debug(
            f"{schema_cls.__name__}: Cached validated schema "
            f"(size: {len(str(json_schema))} bytes, "
            f"compatible: {', '.join(k for k, v in provider_compatibility.items() if v)})"
        )

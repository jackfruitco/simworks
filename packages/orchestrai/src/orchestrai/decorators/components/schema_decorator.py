"""
Core schema decorator.

- Derives & pins identity via IdentityResolver (domain/namespace/group/name via resolver + hints).
- Validates schemas against provider requirements (e.g., OpenAI)
- Tags schemas with provider compatibility metadata
- Caches validated schemas for performance
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


# Provider validation configuration
# Maps provider name to validation settings
PROVIDER_VALIDATION_CONFIG = {
    "openai": {
        "enabled": True,   # Run validation by default
        "strict": True,    # Fail on validation error
        "validator": None,  # Lazy loaded to avoid circular imports
    },
    # Future providers can be added here:
    # "anthropic": {
    #     "enabled": False,
    #     "strict": False,
    #     "validator": validate_anthropic_schema,
    # },
}


def _get_openai_validator():
    """Lazy load OpenAI validator to avoid circular imports."""
    if PROVIDER_VALIDATION_CONFIG["openai"]["validator"] is None:
        try:
            from orchestrai.contrib.provider_backends.openai.schema.validate import (
                validate_openai_schema
            )
            PROVIDER_VALIDATION_CONFIG["openai"]["validator"] = validate_openai_schema
        except ImportError:
            logger.warning("OpenAI schema validator not found, skipping validation")
            PROVIDER_VALIDATION_CONFIG["openai"]["enabled"] = False
    return PROVIDER_VALIDATION_CONFIG["openai"]["validator"]


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

        # Validate schema and tag with provider compatibility
        self._validate_and_tag_schema(candidate)

        super().register(candidate)

    def _validate_and_tag_schema(self, candidate: Type[Any]) -> None:
        """Validate schema against enabled providers and tag with compatibility metadata.

        This method:
        1. Generates JSON Schema from Pydantic model
        2. Validates schema against enabled providers
        3. Tags schema with provider compatibility metadata
        4. Caches validated schema for performance

        Raises:
            ValueError: If schema fails validation (when strict=True)
        """
        # Generate JSON Schema from Pydantic model
        # Check if candidate has model_json_schema method (Pydantic v2)
        if not hasattr(candidate, 'model_json_schema'):
            logger.debug(f"Schema {candidate.__name__} does not have model_json_schema, skipping validation")
            return

        try:
            schema_json = candidate.model_json_schema()
        except Exception as e:
            logger.warning(f"Failed to generate JSON schema for {candidate.__name__}: {e}")
            return

        # Run provider validations
        compatibility = {}

        for provider, config in PROVIDER_VALIDATION_CONFIG.items():
            if not config["enabled"]:
                continue

            # Lazy load validator
            if provider == "openai":
                validator = _get_openai_validator()
            else:
                validator = config.get("validator")

            if validator is None:
                logger.debug(f"No validator found for {provider}, skipping")
                continue

            strict = config["strict"]

            try:
                is_compatible = validator(schema_json, candidate.__name__, strict=strict)
                compatibility[provider] = is_compatible
                logger.debug(f"Schema {candidate.__name__} validated for {provider}: {is_compatible}")
            except ValueError as e:
                # Validation failed and strict=True raised error
                compatibility[provider] = False
                logger.error(f"Schema {candidate.__name__} failed {provider} validation: {e}")
                raise  # Re-raise for fail-fast behavior
            except Exception as e:
                # Unexpected error during validation
                logger.warning(f"Unexpected error validating {candidate.__name__} for {provider}: {e}")
                compatibility[provider] = False
                if strict:
                    raise

        # Tag schema with metadata
        setattr(candidate, '_provider_compatibility', compatibility)
        setattr(candidate, '_validated_schema', schema_json)
        setattr(candidate, '_validated_at', 'decoration')

        # Cache for performance (avoid regenerating schema)
        # This is used by codecs to skip schema generation at request time
        setattr(candidate, '_cached_openai_schema', schema_json)

        logger.debug(
            f"Schema {candidate.__name__} tagged with compatibility: {compatibility}"
        )

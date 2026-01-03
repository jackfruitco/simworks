"""OpenAI Responses API schema validation rules."""

import json
import logging
from typing import Callable, Tuple

logger = logging.getLogger(__name__)

# Type alias for validator functions
# Returns: (is_valid: bool, error_message: str)
ValidatorFunc = Callable[[dict, str], Tuple[bool, str]]


# Configuration
SCHEMA_SIZE_WARNING_THRESHOLD = 10_000  # 10KB


def _root_is_object(schema: dict, name: str) -> Tuple[bool, str]:
    """Validate root schema is type 'object'."""
    schema_type = schema.get("type")
    if schema_type != "object":
        return (
            False,
            f"{name}: Root schema must be type 'object', got '{schema_type}'. "
            f"OpenAI Responses API requires an object at the root level."
        )
    return True, ""


def _no_root_unions(schema: dict, name: str) -> Tuple[bool, str]:
    """Validate no anyOf/oneOf at root level.

    Note: Nested unions ARE supported by OpenAI and should not be rejected.
    """
    if "anyOf" in schema:
        return (
            False,
            f"{name}: Root-level 'anyOf' unions are not supported by OpenAI. "
            f"Nested unions ARE supported. Redesign with discriminated union in a field:\n"
            f"  class {name}(BaseModel):\n"
            f"      item: Annotated[Union[A, B], Field(discriminator='kind')]"
        )

    if "oneOf" in schema:
        return (
            False,
            f"{name}: Root-level 'oneOf' unions are not supported by OpenAI. "
            f"Nested unions ARE supported. Redesign with discriminated union in a field."
        )

    return True, ""


def _has_properties(schema: dict, name: str) -> Tuple[bool, str]:
    """Validate schema has properties field."""
    if "properties" not in schema:
        return (
            False,
            f"{name}: Root schema must have 'properties' field. "
            f"Define at least one field in your Pydantic model."
        )
    return True, ""


def _check_schema_size(schema: dict, name: str) -> Tuple[bool, str]:
    """Warn if schema is very large (may hit token limits).

    This is a warning, not a validation failure.
    """
    schema_json = json.dumps(schema)
    size_bytes = len(schema_json.encode('utf-8'))

    if size_bytes > SCHEMA_SIZE_WARNING_THRESHOLD:
        size_kb = size_bytes / 1024
        logger.warning(
            f"{name}: Schema size is {size_kb:.1f}KB (>{SCHEMA_SIZE_WARNING_THRESHOLD/1024}KB). "
            f"Large schemas may hit token limits or slow down requests."
        )

    # Always pass - this is just a warning
    return True, ""


# Registry of OpenAI validation rules
OPENAI_VALIDATORS: dict[str, ValidatorFunc] = {
    "root_is_object": _root_is_object,
    "no_root_unions": _no_root_unions,
    "has_properties": _has_properties,
    "schema_size": _check_schema_size,
}


def validate_openai_schema(schema: dict, name: str, *, strict: bool = True) -> bool:
    """Validate schema meets OpenAI Responses API requirements.

    Args:
        schema: JSON Schema dict
        name: Schema name for error messages
        strict: If True, raise ValueError on validation failure.
                If False, return bool without raising.

    Returns:
        True if schema is compatible, False otherwise (only if strict=False)

    Raises:
        ValueError: If schema is incompatible and strict=True
    """
    for validator_name, validator_func in OPENAI_VALIDATORS.items():
        is_valid, error_msg = validator_func(schema, name)
        if not is_valid:
            if strict:
                raise ValueError(error_msg)
            return False

    return True

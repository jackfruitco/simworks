"""OpenAI Responses API schema validation rules.

This module validates JSON Schemas for compliance with OpenAI Structured Outputs
strict mode requirements. It integrates with the orchestrai.schema_lint utility
for comprehensive recursive validation.
"""

from typing import Callable, Tuple

# Import comprehensive linter
try:
    from orchestrai.schema_lint import lint_schema, format_violations
    HAS_SCHEMA_LINT = True
except ImportError:
    HAS_SCHEMA_LINT = False

# Type alias for validator functions
# Returns: (is_valid: bool, error_message: str)
ValidatorFunc = Callable[[dict, str], Tuple[bool, str]]


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
    """Validate no anyOf/oneOf at root level."""
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


# Registry of OpenAI validation rules (basic checks only)
OPENAI_VALIDATORS: dict[str, ValidatorFunc] = {
    "root_is_object": _root_is_object,
    "no_root_unions": _no_root_unions,
    "has_properties": _has_properties,
}


def validate_openai_schema(schema: dict, name: str, *, strict: bool = True) -> bool:
    """Validate schema meets OpenAI Responses API requirements.

    This validator performs two levels of validation:
    1. Basic checks (root type, root unions, root properties) - fast fail
    2. Comprehensive recursive lint (if available) - catches nested violations

    Args:
        schema: JSON Schema dict
        name: Schema name for error messages
        strict: If True, raise ValueError on validation failure.
                If False, return bool without raising.

    Returns:
        True if schema is compatible, False otherwise (only if strict=False)

    Raises:
        ValueError: If schema is incompatible and strict=True

    Examples:
        >>> schema = MyModel.model_json_schema()
        >>> validate_openai_schema(schema, "MyModel")  # Raises on error
        True

        >>> is_valid = validate_openai_schema(schema, "MyModel", strict=False)
        >>> if not is_valid:
        ...     print("Schema has violations")
    """
    # Phase 1: Run basic validators (fast fail for common issues)
    for validator_name, validator_func in OPENAI_VALIDATORS.items():
        is_valid, error_msg = validator_func(schema, name)
        if not is_valid:
            if strict:
                raise ValueError(error_msg)
            return False

    # Phase 2: Run comprehensive lint (catches nested violations)
    if HAS_SCHEMA_LINT:
        violations = lint_schema(schema)
        if violations:
            report = format_violations(violations)
            error_msg = (
                f"{name}: Schema violates OpenAI Structured Outputs strict mode.\n\n"
                f"{report}\n\n"
                f"Common fixes:\n"
                f"  - Replace dict[str, Any] with list[Metafield]\n"
                f"  - Ensure all objects have additionalProperties: false\n"
                f"  - Ensure all objects have 'required' containing ALL property keys"
            )
            if strict:
                raise ValueError(error_msg)
            return False

    return True

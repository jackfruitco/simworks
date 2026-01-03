"""
Schema linter for OpenAI Structured Outputs strict mode compliance.

This module provides utilities to detect schema violations that would be rejected
by OpenAI's Structured Outputs API in strict mode.

Usage:
    from orchestrai.schema_lint import lint_schema, SchemaViolation

    violations = lint_schema(my_schema_json)
    if violations:
        for v in violations:
            print(f"{v.path}: {v.message}")
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class SchemaViolation:
    """Represents a schema compliance violation."""
    path: str
    rule: str
    message: str
    suggestion: str | None = None


def lint_schema(schema: dict[str, Any], path: str = "$") -> list[SchemaViolation]:
    """
    Recursively lint a JSON Schema for OpenAI Structured Outputs compliance.

    Args:
        schema: JSON Schema dict to validate
        path: Current JSON path (for error reporting)

    Returns:
        List of SchemaViolation objects (empty if compliant)

    OpenAI Strict Mode Rules:
        1. All objects must have additionalProperties: false
        2. All objects must have "properties" field (even if empty)
        3. All objects must have "required" containing ALL property keys
        4. Arrays must have "items" field
        5. No root-level unions (anyOf/oneOf)
        6. All schema nodes must have "type" field
    """
    violations: list[SchemaViolation] = []

    # Rule 1: Check if this is an object without additionalProperties: false
    if schema.get("type") == "object":
        additional_props = schema.get("additionalProperties")

        if additional_props is None:
            violations.append(SchemaViolation(
                path=path,
                rule="additionalProperties_missing",
                message="Object type must have 'additionalProperties' field",
                suggestion="Add 'additionalProperties': False to this object"
            ))
        elif additional_props is not False:
            if isinstance(additional_props, dict):
                violations.append(SchemaViolation(
                    path=path,
                    rule="additionalProperties_open_map",
                    message=f"additionalProperties is a schema (open map), must be false for strict mode",
                    suggestion="Replace dict[str, T] with list[Metafield] or a strict model"
                ))
            elif additional_props is True:
                violations.append(SchemaViolation(
                    path=path,
                    rule="additionalProperties_true",
                    message="additionalProperties must be false, not true",
                    suggestion="Change additionalProperties to false or use list[Metafield]"
                ))

        # Rule 2: Objects must have properties
        if "properties" not in schema:
            violations.append(SchemaViolation(
                path=path,
                rule="properties_missing",
                message="Object type must have 'properties' field (even if empty)",
                suggestion="Add 'properties': {} or define at least one field"
            ))

        # Rule 3: Required must contain all property keys
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        if properties and set(required) != set(properties.keys()):
            missing = set(properties.keys()) - set(required)
            violations.append(SchemaViolation(
                path=path,
                rule="required_incomplete",
                message=f"'required' must contain all property keys. Missing: {missing}",
                suggestion=f"Add {missing} to 'required' list"
            ))

        # Recurse into properties
        for prop_name, prop_schema in properties.items():
            if isinstance(prop_schema, dict):
                violations.extend(lint_schema(prop_schema, f"{path}.properties.{prop_name}"))

    # Rule 4: Arrays must have items
    elif schema.get("type") == "array":
        if "items" not in schema:
            violations.append(SchemaViolation(
                path=path,
                rule="array_items_missing",
                message="Array type must have 'items' field",
                suggestion="Define the array item schema in 'items'"
            ))
        else:
            # Recurse into items
            items = schema.get("items")
            if isinstance(items, dict):
                violations.extend(lint_schema(items, f"{path}.items"))

    # Rule 5: No root-level unions (only check at root path)
    if path == "$":
        if "anyOf" in schema:
            violations.append(SchemaViolation(
                path=path,
                rule="root_anyOf",
                message="Root-level anyOf (union) not supported by OpenAI strict mode",
                suggestion="Redesign with discriminated union in a field"
            ))
        if "oneOf" in schema:
            violations.append(SchemaViolation(
                path=path,
                rule="root_oneOf",
                message="Root-level oneOf (union) not supported by OpenAI strict mode",
                suggestion="Redesign with discriminated union in a field"
            ))

    # Rule 6: All schema nodes should have type (warning, not always enforced)
    if "type" not in schema and "$ref" not in schema:
        # Check if this is a union with anyOf/oneOf (allowed in nested positions)
        if not any(k in schema for k in ["anyOf", "oneOf", "allOf"]):
            violations.append(SchemaViolation(
                path=path,
                rule="type_missing",
                message="Schema node missing 'type' field (may cause issues)",
                suggestion="Add explicit 'type' field"
            ))

    # Recurse into nested schemas (anyOf/oneOf/allOf if present in non-root)
    for union_key in ["anyOf", "oneOf", "allOf"]:
        if union_key in schema:
            for idx, subschema in enumerate(schema[union_key]):
                if isinstance(subschema, dict):
                    violations.extend(lint_schema(subschema, f"{path}.{union_key}[{idx}]"))

    # Recurse into definitions/defs
    for defs_key in ["definitions", "$defs"]:
        if defs_key in schema:
            for def_name, def_schema in schema[defs_key].items():
                if isinstance(def_schema, dict):
                    violations.extend(lint_schema(def_schema, f"{path}.{defs_key}.{def_name}"))

    return violations


def format_violations(violations: list[SchemaViolation]) -> str:
    """
    Format violations as a human-readable report.

    Args:
        violations: List of SchemaViolation objects

    Returns:
        Formatted string report
    """
    if not violations:
        return "✅ Schema is OpenAI strict mode compliant"

    lines = [f"❌ Found {len(violations)} schema violation(s):\n"]

    for v in violations:
        lines.append(f"  [{v.rule}] {v.path}")
        lines.append(f"    {v.message}")
        if v.suggestion:
            lines.append(f"    💡 {v.suggestion}")
        lines.append("")

    return "\n".join(lines)


def validate_pydantic_schema(schema_cls, strict: bool = True) -> list[SchemaViolation]:
    """
    Validate a Pydantic model class for OpenAI strict mode compliance.

    Args:
        schema_cls: Pydantic model class
        strict: If True, raise ValueError on violations

    Returns:
        List of violations (empty if compliant)

    Raises:
        ValueError: If strict=True and violations found
    """
    schema_json = schema_cls.model_json_schema()
    violations = lint_schema(schema_json)

    if strict and violations:
        report = format_violations(violations)
        raise ValueError(
            f"Schema {schema_cls.__name__} violates OpenAI strict mode:\n{report}"
        )

    return violations

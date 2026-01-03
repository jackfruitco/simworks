"""Tests for OpenAI schema validators."""

import pytest

from orchestrai.contrib.provider_backends.openai.schema.validate import (
    validate_openai_schema,
    _root_is_object,
    _no_root_unions,
    _has_properties,
)


class TestRootIsObjectValidator:
    """Test the root_is_object validator."""

    def test_valid_object_schema(self):
        """Valid object schema should pass."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_invalid_array_schema(self):
        """Root array schema should fail."""
        schema = {"type": "array", "items": {"type": "string"}}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "Root schema must be type 'object'" in error
        assert "got 'array'" in error

    def test_invalid_string_schema(self):
        """Root string schema should fail."""
        schema = {"type": "string"}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "Root schema must be type 'object'" in error
        assert "got 'string'" in error

    def test_invalid_null_type(self):
        """Schema with no type should fail."""
        schema = {"properties": {"name": {"type": "string"}}}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "Root schema must be type 'object'" in error
        assert "got 'None'" in error


class TestNoRootUnionsValidator:
    """Test the no_root_unions validator."""

    def test_valid_object_without_unions(self):
        """Valid object without unions should pass."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_invalid_anyof_at_root(self):
        """Schema with root-level anyOf should fail."""
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "number"}}},
            ]
        }
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is False
        assert "Root-level 'anyOf' unions are not supported" in error
        assert "Nested unions ARE supported" in error
        assert "discriminator" in error

    def test_invalid_oneof_at_root(self):
        """Schema with root-level oneOf should fail."""
        schema = {
            "oneOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "number"}}},
            ]
        }
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is False
        assert "Root-level 'oneOf' unions are not supported" in error
        assert "Nested unions ARE supported" in error

    def test_valid_nested_anyof(self):
        """Nested anyOf should pass (not at root)."""
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"},
                    ]
                }
            },
        }
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is True
        assert error == ""


class TestHasPropertiesValidator:
    """Test the has_properties validator."""

    def test_valid_schema_with_properties(self):
        """Schema with properties should pass."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        is_valid, error = _has_properties(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_invalid_schema_without_properties(self):
        """Schema without properties should fail."""
        schema = {"type": "object"}
        is_valid, error = _has_properties(schema, "TestSchema")
        assert is_valid is False
        assert "must have 'properties' field" in error
        assert "Define at least one field" in error

    def test_valid_schema_with_empty_properties(self):
        """Schema with empty properties dict should pass."""
        schema = {"type": "object", "properties": {}}
        is_valid, error = _has_properties(schema, "TestSchema")
        assert is_valid is True
        assert error == ""


class TestValidateOpenaiSchema:
    """Test the main validate_openai_schema function."""

    def test_valid_schema_passes(self):
        """Valid schema should pass all validators."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "number"},
            },
        }
        result = validate_openai_schema(schema, "TestSchema", strict=True)
        assert result is True

    def test_valid_schema_with_nested_union(self):
        """Valid schema with nested union should pass."""
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "anyOf": [
                        {"type": "object", "properties": {"success": {"type": "boolean"}}},
                        {"type": "object", "properties": {"error": {"type": "string"}}},
                    ]
                }
            },
        }
        result = validate_openai_schema(schema, "TestSchema", strict=True)
        assert result is True

    def test_invalid_schema_strict_mode_raises(self):
        """Invalid schema in strict mode should raise ValueError."""
        schema = {"type": "array", "items": {"type": "string"}}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "Root schema must be type 'object'" in str(exc_info.value)

    def test_invalid_schema_non_strict_returns_false(self):
        """Invalid schema in non-strict mode should return False."""
        schema = {"type": "array", "items": {"type": "string"}}
        result = validate_openai_schema(schema, "TestSchema", strict=False)
        assert result is False

    def test_invalid_root_union_strict_mode_raises(self):
        """Root-level union in strict mode should raise ValueError."""
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "number"}}},
            ]
        }
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "Root-level 'anyOf' unions are not supported" in str(exc_info.value)

    def test_invalid_no_properties_strict_mode_raises(self):
        """Schema without properties in strict mode should raise ValueError."""
        schema = {"type": "object"}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "must have 'properties' field" in str(exc_info.value)

    def test_complex_valid_schema(self):
        """Complex but valid schema should pass."""
        schema = {
            "type": "object",
            "properties": {
                "patient": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "number"},
                    },
                },
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "test": {"type": "string"},
                            "value": {"type": "number"},
                        },
                    },
                },
                "status": {
                    "anyOf": [
                        {"type": "object", "properties": {"success": {"type": "boolean"}}},
                        {"type": "object", "properties": {"error": {"type": "string"}}},
                    ]
                },
            },
        }
        result = validate_openai_schema(schema, "ComplexSchema", strict=True)
        assert result is True

    def test_error_message_includes_schema_name(self):
        """Error messages should include the schema name."""
        schema = {"type": "string"}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "MyCustomSchema", strict=True)
        assert "MyCustomSchema" in str(exc_info.value)

    def test_all_validators_run_in_order(self):
        """All validators should run and first failure should raise."""
        # This schema fails on root_is_object but also missing properties
        schema = {"type": "array"}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        # Should fail on first validator (root_is_object)
        assert "Root schema must be type 'object'" in str(exc_info.value)

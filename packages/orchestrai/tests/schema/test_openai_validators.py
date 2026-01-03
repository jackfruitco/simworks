"""Tests for OpenAI schema validators."""

import pytest
from orchestrai.contrib.provider_backends.openai.schema.validate import (
    validate_openai_schema,
    _root_is_object,
    _no_root_unions,
    _has_properties,
    _check_schema_size,
)


class TestRootIsObject:
    """Tests for _root_is_object validator."""

    def test_valid_object_schema(self):
        """Valid object schema should pass."""
        schema = {"type": "object", "properties": {}}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_root_is_array_fails(self):
        """Root array schema should fail."""
        schema = {"type": "array", "items": {}}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "TestSchema" in error
        assert "must be type 'object'" in error
        assert "got 'array'" in error

    def test_root_is_string_fails(self):
        """Root string schema should fail."""
        schema = {"type": "string"}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "object" in error.lower()

    def test_root_is_null_fails(self):
        """Schema without type should fail."""
        schema = {"properties": {}}
        is_valid, error = _root_is_object(schema, "TestSchema")
        assert is_valid is False


class TestNoRootUnions:
    """Tests for _no_root_unions validator."""

    def test_no_unions_passes(self):
        """Schema without unions should pass."""
        schema = {"type": "object", "properties": {"field": {"type": "string"}}}
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_root_anyof_fails(self):
        """Root-level anyOf should fail."""
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "string"}}},
            ]
        }
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is False
        assert "TestSchema" in error
        assert "anyOf" in error
        assert "not supported" in error
        assert "Nested unions ARE supported" in error

    def test_root_oneof_fails(self):
        """Root-level oneOf should fail."""
        schema = {
            "oneOf": [
                {"type": "object", "properties": {"x": {"type": "number"}}},
                {"type": "object", "properties": {"y": {"type": "number"}}},
            ]
        }
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is False
        assert "oneOf" in error
        assert "not supported" in error

    def test_nested_union_passes(self):
        """Nested anyOf should pass (OpenAI supports nested unions)."""
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"}
                    ]
                }
            }
        }
        is_valid, error = _no_root_unions(schema, "TestSchema")
        assert is_valid is True
        assert error == ""


class TestHasProperties:
    """Tests for _has_properties validator."""

    def test_schema_with_properties_passes(self):
        """Schema with properties should pass."""
        schema = {"type": "object", "properties": {"field": {"type": "string"}}}
        is_valid, error = _has_properties(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_schema_without_properties_fails(self):
        """Schema without properties should fail."""
        schema = {"type": "object"}
        is_valid, error = _has_properties(schema, "TestSchema")
        assert is_valid is False
        assert "properties" in error.lower()
        assert "TestSchema" in error

    def test_empty_properties_passes(self):
        """Schema with empty properties dict should pass."""
        schema = {"type": "object", "properties": {}}
        is_valid, error = _has_properties(schema, "TestSchema")
        assert is_valid is True


class TestCheckSchemaSize:
    """Tests for _check_schema_size validator."""

    def test_small_schema_passes(self):
        """Small schema should pass without warning."""
        schema = {"type": "object", "properties": {"field": {"type": "string"}}}
        is_valid, error = _check_schema_size(schema, "TestSchema")
        assert is_valid is True
        assert error == ""

    def test_large_schema_passes_with_warning(self, caplog):
        """Large schema should pass but log warning."""
        # Create a large schema (>10KB)
        properties = {f"field_{i}": {"type": "string", "description": "x" * 100} for i in range(200)}
        schema = {"type": "object", "properties": properties}

        is_valid, error = _check_schema_size(schema, "TestSchema")

        # Should still pass (warning only)
        assert is_valid is True
        assert error == ""

        # Should log warning
        assert any("Schema size is" in record.message for record in caplog.records)


class TestValidateOpenaiSchema:
    """Tests for validate_openai_schema function."""

    def test_valid_schema_passes(self):
        """Fully valid schema should pass all validators."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name"]
        }
        result = validate_openai_schema(schema, "TestSchema", strict=True)
        assert result is True

    def test_invalid_schema_raises_in_strict_mode(self):
        """Invalid schema should raise ValueError in strict mode."""
        schema = {"type": "array", "items": {}}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "must be type 'object'" in str(exc_info.value)

    def test_invalid_schema_returns_false_in_non_strict_mode(self):
        """Invalid schema should return False in non-strict mode."""
        schema = {"type": "array", "items": {}}
        result = validate_openai_schema(schema, "TestSchema", strict=False)
        assert result is False

    def test_root_union_raises(self):
        """Root union should raise ValueError."""
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "string"}}},
            ]
        }
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "anyOf" in str(exc_info.value)

    def test_missing_properties_raises(self):
        """Schema without properties should raise ValueError."""
        schema = {"type": "object"}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "properties" in str(exc_info.value).lower()

    def test_complex_valid_schema_passes(self):
        """Complex but valid schema should pass."""
        schema = {
            "type": "object",
            "properties": {
                "patient": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"}
                    }
                },
                "result": {
                    "anyOf": [  # Nested union - OK!
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "success"},
                                "data": {"type": "string"}
                            }
                        },
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"const": "error"},
                                "error": {"type": "string"}
                            }
                        }
                    ]
                }
            }
        }
        result = validate_openai_schema(schema, "ComplexSchema", strict=True)
        assert result is True

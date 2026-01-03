"""
Integration tests for OpenAI schema validator with comprehensive lint.

Tests the two-phase validation approach:
1. Basic validators (root checks)
2. Comprehensive lint (recursive checks)
"""

import pytest

from orchestrai.contrib.provider_backends.openai.schema.validate import (
    validate_openai_schema,
    _root_is_object,
    _no_root_unions,
    _has_properties,
)


class TestBasicValidators:
    """Tests for basic validator functions."""

    def test_root_is_object_valid(self):
        """_root_is_object passes for object type."""
        schema = {"type": "object"}
        is_valid, msg = _root_is_object(schema, "TestSchema")
        assert is_valid is True
        assert msg == ""

    def test_root_is_object_invalid_string(self):
        """_root_is_object fails for string type."""
        schema = {"type": "string"}
        is_valid, msg = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "must be type 'object'" in msg
        assert "TestSchema" in msg

    def test_root_is_object_invalid_array(self):
        """_root_is_object fails for array type."""
        schema = {"type": "array"}
        is_valid, msg = _root_is_object(schema, "TestSchema")
        assert is_valid is False
        assert "must be type 'object'" in msg

    def test_no_root_unions_valid(self):
        """_no_root_unions passes when no anyOf/oneOf."""
        schema = {"type": "object"}
        is_valid, msg = _no_root_unions(schema, "TestSchema")
        assert is_valid is True
        assert msg == ""

    def test_no_root_unions_invalid_anyof(self):
        """_no_root_unions fails for root anyOf."""
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        is_valid, msg = _no_root_unions(schema, "TestSchema")
        assert is_valid is False
        assert "anyOf" in msg.lower()
        assert "not supported" in msg

    def test_no_root_unions_invalid_oneof(self):
        """_no_root_unions fails for root oneOf."""
        schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        is_valid, msg = _no_root_unions(schema, "TestSchema")
        assert is_valid is False
        assert "oneOf" in msg.lower()

    def test_has_properties_valid(self):
        """_has_properties passes when properties exists."""
        schema = {"properties": {"name": {"type": "string"}}}
        is_valid, msg = _has_properties(schema, "TestSchema")
        assert is_valid is True

    def test_has_properties_valid_empty(self):
        """_has_properties passes for empty properties."""
        schema = {"properties": {}}
        is_valid, msg = _has_properties(schema, "TestSchema")
        assert is_valid is True

    def test_has_properties_invalid(self):
        """_has_properties fails when properties missing."""
        schema = {"type": "object"}
        is_valid, msg = _has_properties(schema, "TestSchema")
        assert is_valid is False
        assert "must have 'properties'" in msg


class TestValidateOpenAISchemaBasic:
    """Tests for basic validation (phase 1)."""

    def test_validate_basic_compliant_schema(self):
        """Basic compliant schema passes validation."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }
        # Should pass basic validation
        result = validate_openai_schema(schema, "TestSchema", strict=False)
        assert result is True

    def test_validate_rejects_non_object_root(self):
        """Validator rejects non-object root type."""
        schema = {"type": "array", "items": {"type": "string"}}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "must be type 'object'" in str(exc_info.value)

    def test_validate_rejects_root_anyof(self):
        """Validator rejects root-level anyOf."""
        schema = {"anyOf": [{"type": "string"}]}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "anyOf" in str(exc_info.value).lower()

    def test_validate_rejects_missing_properties(self):
        """Validator rejects schema without properties."""
        schema = {"type": "object"}
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "properties" in str(exc_info.value).lower()

    def test_validate_non_strict_returns_false(self):
        """Validator returns False in non-strict mode on error."""
        schema = {"type": "array"}
        result = validate_openai_schema(schema, "TestSchema", strict=False)
        assert result is False


class TestValidateOpenAISchemaComprehensive:
    """Tests for comprehensive lint integration (phase 2)."""

    def test_validate_detects_nested_violations(self):
        """Validator detects nested additionalProperties violations."""
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"}
                    },
                    "required": ["value"]
                    # Missing additionalProperties on nested object
                }
            },
            "required": ["nested"],
            "additionalProperties": False
        }
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        error_msg = str(exc_info.value)
        assert "violates OpenAI Structured Outputs strict mode" in error_msg
        assert "additionalProperties" in error_msg.lower()

    def test_validate_provides_actionable_errors(self):
        """Validator provides actionable error messages."""
        schema = {
            "type": "object",
            "properties": {
                "meta": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            "required": ["meta"],
            "additionalProperties": False
        }
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        error_msg = str(exc_info.value)
        # Should include JSON path
        assert "$.properties.meta" in error_msg or "meta" in error_msg
        # Should include fix suggestions
        assert "Metafield" in error_msg or "additionalProperties" in error_msg.lower()

    def test_validate_detects_incomplete_required(self):
        """Validator detects incomplete required lists."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name"],  # Missing "age"
            "additionalProperties": False
        }
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        assert "required" in str(exc_info.value).lower()

    def test_validate_fully_compliant_schema(self):
        """Fully compliant schema passes both phases."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"}
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["name", "items"],
            "additionalProperties": False
        }
        # Should pass both basic and comprehensive validation
        result = validate_openai_schema(schema, "TestSchema", strict=True)
        assert result is True

    def test_validate_handles_definitions(self):
        """Validator checks $defs recursively."""
        schema = {
            "type": "object",
            "properties": {
                "ref_field": {"$ref": "#/$defs/MyType"}
            },
            "required": ["ref_field"],
            "additionalProperties": False,
            "$defs": {
                "MyType": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"]
                    # Missing additionalProperties in $defs
                }
            }
        }
        with pytest.raises(ValueError) as exc_info:
            validate_openai_schema(schema, "TestSchema", strict=True)
        error_msg = str(exc_info.value)
        assert "$defs" in error_msg or "MyType" in error_msg


class TestValidatorIntegrationWithMetafield:
    """Tests validator with Metafield-based schemas."""

    def test_metafield_schema_passes_validation(self):
        """Metafield schema passes OpenAI validation."""
        from orchestrai.types import Metafield

        schema = Metafield.model_json_schema()
        result = validate_openai_schema(schema, "Metafield", strict=True)
        assert result is True

    def test_list_metafield_schema_passes(self):
        """Schema with list[Metafield] passes validation."""
        from pydantic import BaseModel, Field
        from orchestrai.types import Metafield

        class TestSchema(BaseModel):
            meta: list[Metafield] = Field(default_factory=list)

        schema = TestSchema.model_json_schema()
        result = validate_openai_schema(schema, "TestSchema", strict=True)
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

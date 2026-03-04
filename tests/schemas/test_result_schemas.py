# tests/schemas/test_result_schemas.py
"""
Schema generation tests for Result* types.

Tests that Result* types generate strict JSON Schema compatible with
OpenAI Structured Outputs requirements.
"""

import pytest

from orchestrai.schema_lint import format_violations, lint_schema
from orchestrai.types import (
    ResultImageContent,
    ResultMessageItem,
    ResultMetafield,
    ResultTextContent,
    ResultToolCallContent,
    ResultToolResultContent,
)


class TestResultContentSchemas:
    """Tests for Result* content type schema generation."""

    def test_result_text_content_strict_schema(self):
        """ResultTextContent generates strict JSON Schema."""
        schema = ResultTextContent.model_json_schema()

        # Assert object type
        assert schema["type"] == "object", "Root must be object type"

        # Assert strict mode (additionalProperties: false)
        assert "additionalProperties" in schema
        assert schema["additionalProperties"] is False, "Must have additionalProperties: false"

        # Assert required fields
        assert "required" in schema
        assert set(schema["required"]) == {"type", "text"}, "All properties must be required"

        # Assert properties exist
        assert "properties" in schema
        assert "type" in schema["properties"]
        assert "text" in schema["properties"]

        # Assert type discriminator
        type_schema = schema["properties"]["type"]
        assert type_schema.get("const") == "text" or type_schema.get("enum") == ["text"]

    def test_result_image_content_strict_schema(self):
        """ResultImageContent generates strict JSON Schema."""
        schema = ResultImageContent.model_json_schema()

        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {"type", "mime_type", "data_b64"}

    def test_result_tool_call_content_strict_schema(self):
        """ResultToolCallContent generates strict JSON Schema."""
        schema = ResultToolCallContent.model_json_schema()

        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {"type", "call_id", "name", "arguments_json"}

        # Verify arguments_json is string (not dict)
        args_schema = schema["properties"]["arguments_json"]
        assert args_schema["type"] == "string", "arguments_json must be string for strict mode"

    def test_result_tool_result_content_strict_schema(self):
        """ResultToolResultContent generates strict JSON Schema."""
        schema = ResultToolResultContent.model_json_schema()

        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

        # All fields required (even nullable ones)
        expected_required = {
            "type",
            "call_id",
            "result_text",
            "result_json_str",
            "mime_type",
            "data_b64",
        }
        assert set(schema["required"]) == expected_required


class TestResultMessageSchema:
    """Tests for ResultMessageItem schema generation."""

    def test_result_message_item_strict_schema(self):
        """ResultMessageItem generates strict JSON Schema."""
        schema = ResultMessageItem.model_json_schema()

        # Root assertions
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

        # Required fields
        assert set(schema["required"]) == {"role", "content", "item_meta"}

        # Properties exist
        assert "role" in schema["properties"]
        assert "content" in schema["properties"]
        assert "item_meta" in schema["properties"]

    def test_result_message_content_array(self):
        """ResultMessageItem.content is array of Result* content types."""
        schema = ResultMessageItem.model_json_schema()

        content_schema = schema["properties"]["content"]
        assert content_schema["type"] == "array"
        assert "items" in content_schema

        # Content items should be discriminated union
        items_schema = content_schema["items"]
        # Pydantic unions create anyOf/oneOf
        assert "anyOf" in items_schema or "oneOf" in items_schema

    def test_result_message_item_meta_array(self):
        """ResultMessageItem.item_meta is array of ResultMetafield."""
        schema = ResultMessageItem.model_json_schema()

        item_meta_schema = schema["properties"]["item_meta"]
        assert item_meta_schema["type"] == "array"
        assert "items" in item_meta_schema

        # item_meta items should be ResultMetafield
        items_schema = item_meta_schema["items"]
        assert "$ref" in items_schema  # References ResultMetafield definition


class TestSchemaLintCompliance:
    """Tests that Result* schemas pass schema linting."""

    @pytest.mark.parametrize(
        "schema_cls",
        [
            ResultTextContent,
            ResultImageContent,
            ResultToolCallContent,
            ResultToolResultContent,
            ResultMessageItem,
            ResultMetafield,
        ],
    )
    def test_result_schema_passes_lint(self, schema_cls):
        """All Result* schemas pass OpenAI strict mode linting."""
        schema = schema_cls.model_json_schema()
        violations = lint_schema(schema)

        assert violations == [], (
            f"{schema_cls.__name__} has violations: {format_violations(violations)}"
        )


class TestNestedStrictness:
    """Tests that strictness applies recursively to nested objects."""

    def test_nested_metafield_strict(self):
        """Nested ResultMetafield has additionalProperties: false."""
        schema = ResultMessageItem.model_json_schema()

        # Find Metafield definition in $defs
        assert "$defs" in schema or "definitions" in schema
        defs = schema.get("$defs") or schema.get("definitions")

        metafield_def = None
        for key, value in defs.items():
            if "Metafield" in key:
                metafield_def = value
                break

        assert metafield_def is not None, "ResultMetafield definition not found"
        assert metafield_def.get("additionalProperties") is False

    def test_nested_content_types_strict(self):
        """Nested content types in union have additionalProperties: false."""
        schema = ResultMessageItem.model_json_schema()

        # Find content type definitions
        defs = schema.get("$defs") or schema.get("definitions")

        for def_name, def_schema in defs.items():
            if "Content" in def_name and def_schema.get("type") == "object":
                # Each content type must be strict
                assert def_schema.get("additionalProperties") is False, (
                    f"{def_name} must have additionalProperties: false"
                )


class TestSchemaStability:
    """Tests that schema generation is deterministic."""

    def test_schema_generation_deterministic(self):
        """Repeated schema generation produces same result."""
        schema1 = ResultMessageItem.model_json_schema()
        schema2 = ResultMessageItem.model_json_schema()

        # Schema should be identical
        assert schema1 == schema2, "Schema generation must be deterministic"

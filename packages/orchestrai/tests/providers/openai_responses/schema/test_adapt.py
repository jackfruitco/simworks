"""Tests for OpenAI schema format adapter."""

import json
import pytest

from orchestrai.contrib.provider_backends.openai.schema.adapt import (
    OpenaiFormatAdapter,
    OpenaiBaseSchemaAdapter,
)


class TestOpenaiBaseSchemaAdapter:
    """Test the base adapter class."""

    def test_provider_slug(self):
        """Base adapter should have correct provider slug."""
        adapter = OpenaiBaseSchemaAdapter()
        assert adapter.provider_slug == "openai-prod"


class TestOpenaiFormatAdapter:
    """Test the OpenAI format adapter."""

    def test_adapter_order(self):
        """Format adapter should have order 999 (runs last)."""
        adapter = OpenaiFormatAdapter()
        assert adapter.order == 999

    def test_wraps_simple_schema(self):
        """Adapter should wrap simple schema in OpenAI envelope."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }

        result = adapter.adapt(schema)

        assert "format" in result
        assert result["format"]["type"] == "json_schema"
        assert result["format"]["name"] == "response"
        assert result["format"]["schema"] == schema

    def test_wraps_complex_schema(self):
        """Adapter should wrap complex schema correctly."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "patient": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "number"}
                    }
                },
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "test": {"type": "string"},
                            "value": {"type": "number"}
                        }
                    }
                }
            }
        }

        result = adapter.adapt(schema)

        assert result["format"]["schema"] == schema
        assert result["format"]["type"] == "json_schema"
        assert result["format"]["name"] == "response"

    def test_preserves_schema_content(self):
        """Adapter should preserve all schema content without modification."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "field1": {"type": "string", "description": "Test field"},
                "field2": {"type": "number", "minimum": 0, "maximum": 100}
            },
            "required": ["field1"],
            "additionalProperties": False
        }

        result = adapter.adapt(schema)

        # Schema should be preserved exactly
        assert result["format"]["schema"] == schema
        # Check some specific properties
        assert result["format"]["schema"]["properties"]["field1"]["description"] == "Test field"
        assert result["format"]["schema"]["required"] == ["field1"]

    def test_output_is_json_serializable(self):
        """Adapter output should be JSON serializable."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "number"}
            }
        }

        result = adapter.adapt(schema)

        # Should not raise exception
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

        # Should round-trip correctly
        parsed = json.loads(json_str)
        assert parsed == result

    def test_nested_union_preserved(self):
        """Adapter should preserve nested unions."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "anyOf": [
                        {"type": "object", "properties": {"success": {"type": "boolean"}}},
                        {"type": "object", "properties": {"error": {"type": "string"}}}
                    ]
                }
            }
        }

        result = adapter.adapt(schema)

        # Nested union should be preserved exactly
        assert result["format"]["schema"]["properties"]["result"]["anyOf"] == schema["properties"]["result"]["anyOf"]

    def test_empty_schema(self):
        """Adapter should handle minimal schema."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {}
        }

        result = adapter.adapt(schema)

        assert result["format"]["schema"] == schema
        assert result["format"]["type"] == "json_schema"

    def test_schema_with_definitions(self):
        """Adapter should preserve $defs and references."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "item": {"$ref": "#/$defs/Item"}
            },
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}
                    }
                }
            }
        }

        result = adapter.adapt(schema)

        assert "$defs" in result["format"]["schema"]
        assert result["format"]["schema"]["$defs"]["Item"] == schema["$defs"]["Item"]
        assert result["format"]["schema"]["properties"]["item"]["$ref"] == "#/$defs/Item"

    def test_multiple_adapters_ordering(self):
        """Test that adapter can be ordered with other adapters."""
        adapter1 = OpenaiFormatAdapter()

        # Create a mock adapter with different order
        class MockAdapter(OpenaiBaseSchemaAdapter):
            order = 0

        adapter2 = MockAdapter()

        adapters = [adapter1, adapter2]
        sorted_adapters = sorted(adapters, key=lambda a: a.order)

        # MockAdapter (order 0) should come before OpenaiFormatAdapter (order 999)
        assert sorted_adapters[0].order == 0
        assert sorted_adapters[1].order == 999

    def test_adapter_returns_dict(self):
        """Adapter should return a dictionary."""
        adapter = OpenaiFormatAdapter()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        result = adapter.adapt(schema)

        assert isinstance(result, dict)

    def test_schema_not_modified(self):
        """Original schema should not be modified."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }
        original_schema = schema.copy()

        adapter.adapt(schema)

        # Original should be unchanged
        assert schema == original_schema

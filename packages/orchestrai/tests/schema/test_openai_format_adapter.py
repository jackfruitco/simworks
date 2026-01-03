"""Tests for OpenAI format adapter."""

import json
from orchestrai.contrib.provider_backends.openai.schema.adapt import OpenaiFormatAdapter


class TestOpenaiFormatAdapter:
    """Tests for OpenaiFormatAdapter."""

    def test_adapter_wraps_schema_correctly(self):
        """Adapter should wrap schema in OpenAI format envelope."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "field": {"type": "string"}
            }
        }

        result = adapter.adapt(schema)

        assert result == {
            "format": {
                "type": "json_schema",
                "name": "response",
                "schema": schema
            }
        }

    def test_adapter_preserves_schema_content(self):
        """Adapter should not modify the schema content."""
        adapter = OpenaiFormatAdapter()
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
                "metadata": {
                    "type": "array",
                    "items": {"type": "object"}
                }
            }
        }

        result = adapter.adapt(schema)

        # Original schema should be preserved inside wrapper
        assert result["format"]["schema"] == schema
        assert result["format"]["schema"] is not schema  # Should be same value but potentially different reference

    def test_result_is_json_serializable(self):
        """Result should be JSON-serializable."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {"field": {"type": "string"}}
        }

        result = adapter.adapt(schema)

        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

        # Should round-trip
        parsed = json.loads(json_str)
        assert parsed == result

    def test_adapter_has_correct_order(self):
        """Adapter should have order 999 (runs last)."""
        adapter = OpenaiFormatAdapter()
        assert adapter.order == 999

    def test_adapter_has_correct_provider_slug(self):
        """Adapter should have correct provider slug."""
        adapter = OpenaiFormatAdapter()
        assert adapter.provider_slug == "openai-prod"

    def test_empty_schema_wraps_correctly(self):
        """Even empty schema should wrap correctly."""
        adapter = OpenaiFormatAdapter()
        schema = {"type": "object", "properties": {}}

        result = adapter.adapt(schema)

        assert "format" in result
        assert result["format"]["type"] == "json_schema"
        assert result["format"]["name"] == "response"
        assert result["format"]["schema"] == schema

    def test_complex_nested_schema(self):
        """Complex nested schema should wrap correctly."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }

        result = adapter.adapt(schema)

        # Deep nesting should be preserved
        assert result["format"]["schema"]["properties"]["level1"]["properties"]["level2"]["properties"]["level3"]["type"] == "string"

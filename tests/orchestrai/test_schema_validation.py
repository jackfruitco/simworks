"""Tests for OrchestrAI schema validation and codec integration.

Validates:
- Schema decorator behavior
- Codec OpenAI request construction
- Format adapter correctness
"""

import pytest

from orchestrai.contrib.provider_codecs.openai.responses_json import OpenAIResponsesJsonCodec
from orchestrai.contrib.provider_backends.openai.schema.adapt import OpenaiFormatAdapter
from orchestrai.types import Request
from chatlab.orca.schemas import PatientInitialOutputSchema


class TestSchemaDecorator:
    """Tests for @schema decorator validation."""

    def test_decorator_tags_schema_with_compatibility(self):
        """Verify @schema decorator adds compatibility metadata."""
        assert hasattr(PatientInitialOutputSchema, "_provider_compatibility")

        compatibility = PatientInitialOutputSchema._provider_compatibility
        assert isinstance(compatibility, dict)
        assert compatibility.get("openai") is True

    def test_decorator_caches_validated_schema(self):
        """Verify @schema decorator caches JSON schema."""
        assert hasattr(PatientInitialOutputSchema, "_validated_schema")

        cached_schema = PatientInitialOutputSchema._validated_schema
        assert isinstance(cached_schema, dict)
        assert cached_schema["type"] == "object"
        assert "properties" in cached_schema

    def test_decorator_marks_validation_time(self):
        """Verify schema validation happens at decoration time."""
        assert hasattr(PatientInitialOutputSchema, "_validated_at")
        assert PatientInitialOutputSchema._validated_at == "decoration"


class TestCodecOpenAIIntegration:
    """Tests for codec OpenAI request construction."""

    @pytest.mark.asyncio
    async def test_codec_builds_openai_request_format(self):
        """Verify codec wraps schema in OpenAI format envelope."""
        req = Request(
            messages=[],
            response_schema=PatientInitialOutputSchema,
        )

        codec = OpenAIResponsesJsonCodec()
        await codec.aencode(req)

        # Verify format envelope created
        assert hasattr(req, "provider_response_format")
        provider_format = req.provider_response_format

        assert "format" in provider_format
        assert provider_format["format"]["type"] == "json_schema"
        assert provider_format["format"]["name"] == "response"
        assert "schema" in provider_format["format"]

        # Verify schema structure
        schema = provider_format["format"]["schema"]
        assert schema["type"] == "object"
        assert "properties" in schema

    @pytest.mark.asyncio
    async def test_codec_checks_compatibility(self):
        """Verify codec checks schema was validated for OpenAI."""
        from orchestrai.components.codecs.exceptions import CodecSchemaError
        from pydantic import BaseModel

        # Create undecorated schema (no compatibility metadata)
        class UnvalidatedSchema(BaseModel):
            name: str

        req = Request(
            messages=[],
            response_schema=UnvalidatedSchema,
        )

        codec = OpenAIResponsesJsonCodec()

        # Should raise error for unvalidated schema
        with pytest.raises(CodecSchemaError) as exc_info:
            await codec.aencode(req)

        assert "not validated for OpenAI" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_codec_uses_cached_schema(self):
        """Verify codec uses cached schema instead of regenerating."""
        req = Request(
            messages=[],
            response_schema=PatientInitialOutputSchema,
        )

        codec = OpenAIResponsesJsonCodec()
        await codec.aencode(req)

        # Verify request has original schema for diagnostics
        assert hasattr(req, "response_schema_json")
        assert req.response_schema_json == PatientInitialOutputSchema._validated_schema


class TestFormatAdapter:
    """Tests for OpenaiFormatAdapter."""

    def test_adapter_wraps_schema_correctly(self):
        """Verify format adapter produces correct OpenAI envelope."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        result = adapter.adapt(schema)

        # Verify wrapper structure
        assert "format" in result
        assert result["format"]["type"] == "json_schema"
        assert result["format"]["name"] == "response"
        assert result["format"]["schema"] == schema

    def test_adapter_preserves_schema_content(self):
        """Verify adapter doesn't modify original schema."""
        adapter = OpenaiFormatAdapter()
        schema = {
            "type": "object",
            "properties": {
                "field1": {"type": "string", "description": "Test"},
                "field2": {"type": "number", "minimum": 0},
            },
            "required": ["field1"],
            "additionalProperties": False,
        }

        result = adapter.adapt(schema)

        # Original schema should be preserved exactly
        assert result["format"]["schema"] == schema
        assert result["format"]["schema"]["properties"]["field1"]["description"] == "Test"
        assert result["format"]["schema"]["required"] == ["field1"]

    def test_adapter_order(self):
        """Verify adapter runs last (order=999)."""
        adapter = OpenaiFormatAdapter()
        assert adapter.order == 999

    def test_adapter_produces_json_serializable(self):
        """Verify adapter output is JSON serializable."""
        import json

        adapter = OpenaiFormatAdapter()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        result = adapter.adapt(schema)

        # Should not raise exception
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

        # Should round-trip correctly
        parsed = json.loads(json_str)
        assert parsed == result

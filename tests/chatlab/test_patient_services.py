"""Integration tests for chatlab patient services.

Tests:
- Service attribute configuration (response_schema)
- Required context keys
- Schema validation at service boundary
"""

import pytest

from apps.chatlab.orca.services.patient import (
    GenerateInitialResponse,
    GenerateReplyResponse,
    GenerateImageResponse,
)
from apps.chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
)


class TestGenerateInitialResponseService:
    """Tests for GenerateInitialResponse service configuration."""

    def test_service_has_response_schema(self):
        """Verify response_schema attribute is correctly set."""
        assert hasattr(GenerateInitialResponse, "response_schema")
        assert GenerateInitialResponse.response_schema == PatientInitialOutputSchema

    def test_service_required_context_keys(self):
        """Verify simulation_id is a required context key."""
        assert hasattr(GenerateInitialResponse, "required_context_keys")
        assert "simulation_id" in GenerateInitialResponse.required_context_keys

    def test_service_has_prompt_plan(self):
        """Verify prompt_plan is defined."""
        assert hasattr(GenerateInitialResponse, "prompt_plan")
        assert len(GenerateInitialResponse.prompt_plan) > 0


class TestGenerateReplyResponseService:
    """Tests for GenerateReplyResponse service configuration."""

    def test_service_has_response_schema(self):
        """Verify response_schema attribute is correctly set (not response_format_cls)."""
        assert hasattr(GenerateReplyResponse, "response_schema")
        assert GenerateReplyResponse.response_schema == PatientReplyOutputSchema

    def test_service_does_not_have_response_format_cls(self):
        """Verify deprecated response_format_cls is not used."""
        # response_format_cls should not exist or should be None
        response_format_cls = getattr(GenerateReplyResponse, "response_format_cls", None)
        assert response_format_cls is None, (
            "GenerateReplyResponse should use 'response_schema', not 'response_format_cls'. "
            "The framework only recognizes 'response_schema' for schema validation."
        )

    def test_service_required_context_keys(self):
        """Verify simulation_id is a required context key."""
        assert hasattr(GenerateReplyResponse, "required_context_keys")
        assert "simulation_id" in GenerateReplyResponse.required_context_keys


class TestGenerateImageResponseService:
    """Tests for GenerateImageResponse service configuration."""

    def test_service_required_context_keys(self):
        """Verify simulation_id is a required context key."""
        assert hasattr(GenerateImageResponse, "required_context_keys")
        assert "simulation_id" in GenerateImageResponse.required_context_keys


class TestSchemaSerializability:
    """Tests for schema JSON serializability (persistence requirement)."""

    def test_initial_schema_model_dump_is_serializable(self):
        """Verify PatientInitialOutputSchema can be serialized to JSON."""
        import json

        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello"}],
                    "item_meta": [],
                }
            ],
            "metadata": [],
            "llm_conditions_check": [],
        }

        parsed = PatientInitialOutputSchema.model_validate(sample_output)
        dumped = parsed.model_dump(mode="json")

        # Should be JSON serializable without custom encoders
        json_str = json.dumps(dumped)
        assert json_str is not None
        assert "Hello" in json_str

    def test_reply_schema_model_dump_is_serializable(self):
        """Verify PatientReplyOutputSchema can be serialized to JSON."""
        import json

        sample_output = {
            "image_requested": False,
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Reply text"}],
                    "item_meta": [],
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientReplyOutputSchema.model_validate(sample_output)
        dumped = parsed.model_dump(mode="json")

        # Should be JSON serializable without custom encoders
        json_str = json.dumps(dumped)
        assert json_str is not None
        assert "Reply text" in json_str
        assert "image_requested" in json_str
